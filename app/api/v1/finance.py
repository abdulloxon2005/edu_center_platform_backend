from datetime import date
from io import BytesIO
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.models.models import (
    Payment, Expense, User, UserRole, Group, GroupStudent, Course,
    TeacherPayroll, StudentBilling, Invoice, ParentStudent
)
from app.schemas.schemas import (
    PaymentCreate, PaymentResponse, PaymentUpdate, ExpenseCreate, ExpenseResponse,
    PayrollCalculateRequest, PayrollPayRequest, TeacherPayrollResponse,
    StudentBillingGenerateRequest, StudentBillingResponse, DebtorResponse,
    InvoiceCreate, InvoiceResponse, StudentBillingInfoResponse,
    StudentGroupCourseInfo, PaymentRecordResult
)
from app.api.deps import get_current_admin, get_current_user
from app.services.notification import send_telegram_notification

router = APIRouter()


async def sync_student_billing(db: AsyncSession, student_id: int, month_for: str) -> Optional[StudentBilling]:
    """O'quvchining ko'rsatilgan oy bo'yicha to'lovlari asosida StudentBilling yozuvini aniq sinxronizatsiya qilish"""
    # 1. Ushbu oy uchun to'langan barcha summalar (Payment jadvalining o'zidan)
    pay_res = await db.execute(
        select(func.sum(Payment.amount)).where(
            Payment.student_id == student_id,
            Payment.month_for == month_for
        )
    )
    total_paid_for_month = pay_res.scalar() or 0.0

    # 2. O'quvchining faol guruhlari va oylik to'lovi
    stmt = (
        select(GroupStudent, Group, Course)
        .join(Group, GroupStudent.group_id == Group.id)
        .join(Course, Group.course_id == Course.id)
        .where(
            GroupStudent.student_id == student_id,
            GroupStudent.is_active == True,
            Group.is_active == True
        )
    )
    res_groups = await db.execute(stmt)
    active_rows = res_groups.all()
    total_monthly_fee = sum(crs.price_monthly for _, _, crs in active_rows)
    group_id = active_rows[0][1].id if active_rows else 1

    # 3. StudentBilling yozuvlarini qidirish
    billing_res = await db.execute(
        select(StudentBilling).where(
            StudentBilling.student_id == student_id,
            StudentBilling.month_for == month_for
        )
    )
    billings = billing_res.scalars().all()

    if not billings:
        if total_paid_for_month > 0 or total_monthly_fee > 0:
            due = total_monthly_fee if total_monthly_fee > 0 else total_paid_for_month
            billing = StudentBilling(
                student_id=student_id,
                group_id=group_id,
                month_for=month_for,
                amount_due=due,
                amount_paid=total_paid_for_month,
                is_paid=(total_paid_for_month >= due and due > 0),
                due_date=date.today()
            )
            db.add(billing)
            await db.flush()
            return billing
        return None
    else:
        primary_billing = billings[0]
        total_due = sum(b.amount_due for b in billings)
        if total_due <= 0:
            total_due = total_monthly_fee if total_monthly_fee > 0 else total_paid_for_month

        primary_billing.amount_paid = total_paid_for_month
        primary_billing.is_paid = (total_paid_for_month >= total_due and total_due > 0)

        for b in billings[1:]:
            b.amount_paid = 0.0
            b.is_paid = primary_billing.is_paid

        await db.flush()
        return primary_billing


# ----------------------------------------------------
# 1. STUDENT BILLING INFO & DETAILS
# ----------------------------------------------------
@router.get("/student/{student_id}/billing-info", response_model=StudentBillingInfoResponse)
async def get_student_billing_info(
    student_id: int,
    month_for: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """O'quvchining kurslari, oylik to'lov summasi, tanlangan oy bo'yicha to'langan summa va qarz/haqdorlik hisoboti"""
    if current_user.role == UserRole.STUDENT and current_user.id != student_id:
        raise HTTPException(status_code=403, detail="Ruxsat berilmagan!")

    if not month_for:
        month_for = date.today().strftime("%Y-%m")

    # 1. O'quvchini tekshirish
    st_res = await db.execute(select(User).where(User.id == student_id, User.role == UserRole.STUDENT))
    student = st_res.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="O'quvchi topilmadi!")

    # 2. O'quvchi biriktirilgan faol guruhlar va kurslar
    stmt = (
        select(GroupStudent, Group, Course)
        .join(Group, GroupStudent.group_id == Group.id)
        .join(Course, Group.course_id == Course.id)
        .where(
            GroupStudent.student_id == student_id,
            GroupStudent.is_active == True,
            Group.is_active == True
        )
    )
    res = await db.execute(stmt)
    rows = res.all()

    groups_info = []
    total_monthly_fee = 0.0
    for gs, grp, crs in rows:
        groups_info.append(StudentGroupCourseInfo(
            group_id=grp.id,
            group_name=grp.name,
            course_id=crs.id,
            course_title=crs.title,
            price_monthly=crs.price_monthly
        ))
        total_monthly_fee += crs.price_monthly

    # 3. Tanlangan oy bo'yicha StudentBilling ni sinxronlashtirish va olish
    await sync_student_billing(db, student_id, month_for)
    await db.commit()

    # O'sha oy uchun to'langan aniq summa (Payment jadvalidan)
    month_pay_res = await db.execute(
        select(func.sum(Payment.amount)).where(
            Payment.student_id == student_id,
            Payment.month_for == month_for
        )
    )
    month_amount_paid = month_pay_res.scalar() or 0.0

    billing_res = await db.execute(
        select(StudentBilling).where(
            StudentBilling.student_id == student_id,
            StudentBilling.month_for == month_for
        )
    )
    billings = billing_res.scalars().all()
    if billings:
        month_amount_due = sum(b.amount_due for b in billings)
    else:
        month_amount_due = total_monthly_fee

    month_remaining_due = max(0.0, month_amount_due - month_amount_paid)

    # 4. Barcha oylar bo'yicha qarz / haqdorlik balansi
    all_billings_res = await db.execute(
        select(StudentBilling).where(StudentBilling.student_id == student_id)
    )
    all_billings = all_billings_res.scalars().all()
    all_due = sum(b.amount_due for b in all_billings) if all_billings else total_monthly_fee

    payments_res = await db.execute(
        select(func.sum(Payment.amount)).where(Payment.student_id == student_id)
    )
    total_payments_sum = payments_res.scalar() or 0.0

    net_balance = total_payments_sum - all_due
    total_debt = abs(net_balance) if net_balance < 0 else 0.0
    total_credit = net_balance if net_balance > 0 else 0.0

    return StudentBillingInfoResponse(
        student_id=student.id,
        student_name=student.full_name,
        login_id=student.login_id,
        phone=student.phone,
        telegram_chat_id=student.telegram_chat_id,
        groups=groups_info,
        total_monthly_fee=total_monthly_fee,
        month_for=month_for,
        month_amount_due=month_amount_due,
        month_amount_paid=month_amount_paid,
        month_remaining_due=month_remaining_due,
        total_debt=total_debt,
        total_credit=total_credit,
        net_balance=net_balance
    )


@router.get("/group/{group_id}/students-billing")
async def get_group_students_billing(
    group_id: int,
    month_for: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Guruhdagi barcha o'quvchilarning tanlangan oy bo'yicha to'lov va qarzdorlik holati (O'qituvchi va Admin uchun)"""
    if not month_for:
        month_for = date.today().strftime("%Y-%m")

    # 1. Guruhni tekshirish
    g_res = await db.execute(
        select(Group, Course)
        .outerjoin(Course, Group.course_id == Course.id)
        .where(Group.id == group_id)
    )
    grow = g_res.first()
    if not grow:
        raise HTTPException(status_code=404, detail="Guruh topilmadi!")
    group, course = grow
    course_price = course.price_monthly if course else 500000.0

    # 2. Guruhdagi faol talabalar
    st_stmt = (
        select(User)
        .join(GroupStudent, GroupStudent.student_id == User.id)
        .where(
            GroupStudent.group_id == group_id,
            GroupStudent.is_active == True,
            User.is_active == True
        )
        .order_by(User.full_name.asc())
    )
    st_res = await db.execute(st_stmt)
    students = st_res.scalars().all()

    result = []
    for student in students:
        # Billing sinxronizatsiya
        await sync_student_billing(db, student.id, month_for)
        
        # Ushbu oy uchun to'langan jami summa (Payment jadvalidan)
        month_pay_stmt = select(func.sum(Payment.amount)).where(
            Payment.student_id == student.id,
            Payment.month_for == month_for
        )
        month_pay_res = await db.execute(month_pay_stmt)
        total_paid_this_month = month_pay_res.scalar() or 0.0

        # Ushbu guruh uchun oylik to'lov summasi
        b_stmt = select(StudentBilling).where(
            StudentBilling.student_id == student.id,
            StudentBilling.group_id == group_id,
            StudentBilling.month_for == month_for
        )
        b_res = await db.execute(b_stmt)
        billing_record = b_res.scalar_one_or_none()
        expected_fee = billing_record.amount_due if billing_record else course_price

        amount_paid = min(total_paid_this_month, expected_fee)
        remaining_due = max(0.0, expected_fee - amount_paid)
        is_paid = amount_paid >= expected_fee
        is_partial = 0 < amount_paid < expected_fee

        # Barcha oylar bo'yicha umumiy qarzdorlik
        all_billings_res = await db.execute(
            select(StudentBilling).where(StudentBilling.student_id == student.id)
        )
        all_billings = all_billings_res.scalars().all()
        all_due = sum(b.amount_due for b in all_billings) if all_billings else expected_fee

        payments_res = await db.execute(
            select(func.sum(Payment.amount)).where(Payment.student_id == student.id)
        )
        total_payments_sum = payments_res.scalar() or 0.0
        net_balance = total_payments_sum - all_due
        total_debt = abs(net_balance) if net_balance < 0 else 0.0
        total_credit = net_balance if net_balance > 0 else 0.0

        result.append({
            "student_id": student.id,
            "full_name": student.full_name,
            "login_id": student.login_id,
            "phone": student.phone,
            "parent_phone": student.parent_phone,
            "month_for": month_for,
            "expected_fee": expected_fee,
            "amount_paid": amount_paid,
            "remaining_due": remaining_due,
            "is_paid": is_paid,
            "is_partial": is_partial,
            "total_debt": total_debt,
            "total_credit": total_credit,
            "net_balance": net_balance,
            "status": "PAID" if is_paid else "PARTIAL" if is_partial else "UNPAID"
        })

    await db.commit()
    return result


# ----------------------------------------------------
# 2. RECORD PAYMENT & TELEGRAM NOTIFICATION
# ----------------------------------------------------
@router.post("/payments", response_model=PaymentRecordResult)
async def record_payment(
    payment_in: PaymentCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    # O'quvchini tekshirish
    res = await db.execute(select(User).where(User.id == payment_in.student_id, User.role == UserRole.STUDENT))
    student = res.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="O'quvchi topilmadi!")

    # Guruh/kurs narxini aniqlash
    stmt = (
        select(GroupStudent, Group, Course)
        .join(Group, GroupStudent.group_id == Group.id)
        .join(Course, Group.course_id == Course.id)
        .where(
            GroupStudent.student_id == student.id,
            GroupStudent.is_active == True,
            Group.is_active == True
        )
    )
    res_groups = await db.execute(stmt)
    active_rows = res_groups.all()
    total_monthly_fee = sum(crs.price_monthly for _, _, crs in active_rows)
    course_names = ", ".join([f"{crs.title} ({grp.name})" for _, grp, crs in active_rows]) or "Kurs"

    # Yangi to'lovni bazaga kiritish
    payment = Payment(**payment_in.model_dump())
    db.add(payment)
    await db.commit()
    await db.refresh(payment)

    # Billing hisobini sinxronlashtirish
    billing = await sync_student_billing(db, payment_in.student_id, payment_in.month_for)
    await db.commit()
    if billing:
        await db.refresh(billing)
        total_due_amount = billing.amount_due
        total_paid_amount = billing.amount_paid
    else:
        total_due_amount = total_monthly_fee if total_monthly_fee > 0 else payment_in.amount
        total_paid_amount = payment_in.amount

    # Hisob-kitob (qarz yoki haqdorlik)
    diff = total_paid_amount - total_due_amount
    if diff < 0:
        remaining_debt = abs(diff)
        credit_amount = 0.0
        status_note = f"⚠️ Qolgan qarz: {remaining_debt:,.0f} so'm"
    elif diff > 0:
        remaining_debt = 0.0
        credit_amount = diff
        status_note = f"✨ Haqdor (Ortiqcha to'lov): +{credit_amount:,.0f} so'm"
    else:
        remaining_debt = 0.0
        credit_amount = 0.0
        status_note = "✅ To'lov to'liq amalga oshirildi (Qarz yo'q)"

    # Telegram xabarnoma (Rasmiy to'lov cheki) yuborish
    telegram_sent = False
    payment_time_str = payment.created_at.strftime('%Y-%m-%d %H:%M') if hasattr(payment, 'created_at') and payment.created_at else date.today().strftime('%Y-%m-%d')
    note_line = f"💬 Izoh: {payment.note}\n" if payment.note else ""
    
    tg_msg = (
        f"🧾 <b>RASMIY TO'LOV CHEKI #{payment.id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏢 <b>Ta'lim Plus Education Center</b>\n"
        f"👤 O'quvchi: <b>{student.full_name}</b> (ID: <code>{student.login_id}</code>)\n"
        f"📚 Kurs(lar): <b>{course_names}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 <b>To'langan summa: {payment.amount:,.0f} so'm</b>\n"
        f"📅 To'lov oyi: <b>{payment.month_for}</b>\n"
        f"💳 To'lov turi: <b>{payment.payment_method}</b>\n"
        f"🕒 Sana va vaqt: <b>{payment_time_str}</b>\n"
        f"{note_line}"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>HISOB-KITOB HOLATI:</b>\n"
        f"🔹 Talab etilgan oylik summa: <b>{total_due_amount:,.0f} so'm</b>\n"
        f"🔹 Shu oyda jami to'landi: <b>{total_paid_amount:,.0f} so'm</b>\n"
        f"🔹 Natija: <b>{status_note}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ <i>To'lovingiz muvaffaqiyatli qabul qilindi. Ta'lim Plus'ni tanlaganingiz uchun tashakkur!</i>"
    )

    if student.telegram_chat_id:
        telegram_sent = await send_telegram_notification(student.telegram_chat_id, tg_msg)

    # Agar o'quvchiga ota-onasi bog'langan bo'lsa, ularga ham chek yuborish
    try:
        parent_links = await db.execute(
            select(User).join(ParentStudent, ParentStudent.parent_id == User.id)
            .where(ParentStudent.student_id == student.id, User.telegram_chat_id.isnot(None))
        )
        parents = parent_links.scalars().all()
        for p in parents:
            if p.telegram_chat_id and p.telegram_chat_id != student.telegram_chat_id:
                p_sent = await send_telegram_notification(p.telegram_chat_id, tg_msg)
                if p_sent:
                    telegram_sent = True
    except Exception as e:
        pass

    res_message = f"'{student.full_name}'dan {payment.amount:,.0f} so'm to'lov qabul qilindi. {status_note}"
    if telegram_sent:
        res_message += " (Telegramga rasmiy chek yuborildi 🧾)"

    return PaymentRecordResult(
        message=res_message,
        payment_id=payment.id,
        student_name=student.full_name,
        amount_paid=payment.amount,
        month_for=payment.month_for,
        total_due=total_due_amount,
        remaining_debt=remaining_debt,
        credit_amount=credit_amount,
        telegram_notified=telegram_sent
    )


@router.put("/payments/{payment_id}", response_model=PaymentResponse)
async def update_payment(
    payment_id: int,
    payment_in: PaymentUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """Mavjud to'lov ma'lumotlarini tahrirlash va hisob-kitoblarni qayta yangilash"""
    res = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = res.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="To'lov topilmadi!")

    old_month = payment.month_for
    student_id = payment.student_id

    update_data = payment_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(payment, field, value)

    new_month = payment.month_for

    await db.commit()
    await db.refresh(payment)

    # Billing sinxronizatsiyasi: eski va yangi oylar uchun
    await sync_student_billing(db, student_id, old_month)
    if new_month != old_month:
        await sync_student_billing(db, student_id, new_month)
    await db.commit()

    return payment


@router.delete("/payments/{payment_id}")
async def delete_payment(
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """To'lovni o'chirish va tegishli oylik to'lov/qarz hisob-kitobini yangilash"""
    res = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = res.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="To'lov topilmadi!")

    student_id = payment.student_id
    month_for = payment.month_for

    await db.delete(payment)
    await db.commit()

    # O'chirilgan to'lovdan so'ng billing hisobini qayta sinxronlashtirish
    await sync_student_billing(db, student_id, month_for)
    await db.commit()

    return {"message": "To'lov muvaffaqiyatli o'chirildi!", "payment_id": payment_id}


@router.get("/payments", response_model=List[PaymentResponse])
async def list_payments(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    res = await db.execute(select(Payment).order_by(Payment.created_at.desc()))
    return res.scalars().all()


@router.get("/student/{student_id}/payments", response_model=List[PaymentResponse])
async def get_student_payments(
    student_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    res = await db.execute(select(Payment).where(Payment.student_id == student_id).order_by(Payment.created_at.desc()))
    return res.scalars().all()


@router.post("/expenses", response_model=ExpenseResponse)
async def record_expense(
    expense_in: ExpenseCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    expense = Expense(**expense_in.model_dump())
    db.add(expense)
    await db.commit()
    await db.refresh(expense)
    return expense


@router.get("/expenses", response_model=List[ExpenseResponse])
async def list_expenses(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    res = await db.execute(select(Expense).order_by(Expense.date.desc()))
    return res.scalars().all()


# ----------------------------------------------------
# 3. TEACHER PAYROLL (O'QITUVCHILAR MAOSHI)
# ----------------------------------------------------
@router.post("/payroll/calculate", response_model=TeacherPayrollResponse)
async def calculate_teacher_payroll(
    req: PayrollCalculateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """O'qituvchining ko'rsatilgan oy uchun guruhlar tushumidan kelib chiqib maoshini hisoblash"""
    teacher_res = await db.execute(select(User).where(User.id == req.teacher_id, User.role == UserRole.TEACHER))
    teacher = teacher_res.scalar_one_or_none()
    if not teacher:
        raise HTTPException(status_code=404, detail="O'qituvchi topilmadi!")

    groups_res = await db.execute(select(Group).where(Group.teacher_id == req.teacher_id))
    groups = groups_res.scalars().all()
    group_ids = [g.id for g in groups]

    total_group_income = 0.0
    if group_ids:
        students_stmt = select(GroupStudent.student_id).where(GroupStudent.group_id.in_(group_ids))
        st_res = await db.execute(students_stmt)
        student_ids = list(set(st_res.scalars().all()))

        if student_ids:
            p_stmt = select(func.sum(Payment.amount)).where(
                Payment.student_id.in_(student_ids),
                Payment.month_for == req.month_for
            )
            income_res = await db.execute(p_stmt)
            total_group_income = income_res.scalar() or 0.0

    calculated_salary = total_group_income * (req.percentage_rate / 100.0)

    pr_res = await db.execute(
        select(TeacherPayroll).where(
            TeacherPayroll.teacher_id == req.teacher_id,
            TeacherPayroll.month_for == req.month_for
        )
    )
    payroll = pr_res.scalar_one_or_none()
    if not payroll:
        payroll = TeacherPayroll(
            teacher_id=req.teacher_id,
            month_for=req.month_for,
            percentage_rate=req.percentage_rate,
            calculated_salary=calculated_salary
        )
        db.add(payroll)
    else:
        payroll.percentage_rate = req.percentage_rate
        payroll.calculated_salary = calculated_salary

    await db.commit()
    await db.refresh(payroll)
    return payroll


@router.post("/payroll/pay")
async def pay_teacher_salary(
    req: PayrollPayRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    res = await db.execute(select(TeacherPayroll).where(TeacherPayroll.id == req.payroll_id))
    payroll = res.scalar_one_or_none()
    if not payroll:
        raise HTTPException(status_code=404, detail="Maosh yozuvi topilmadi!")

    teacher_res = await db.execute(select(User).where(User.id == payroll.teacher_id))
    teacher = teacher_res.scalar_one_or_none()

    payroll.paid_amount += req.amount
    if payroll.paid_amount >= payroll.calculated_salary:
        payroll.status = "PAID"
    if req.note:
        payroll.note = req.note

    expense = Expense(
        title=f"O'qituvchi Maoshi: {teacher.full_name if teacher else 'Ustoz'} ({payroll.month_for})",
        amount=req.amount,
        category="O'qituvchi Maoshi",
        date=date.today(),
        description=req.note or f"Maosh to'lovi ({payroll.month_for})"
    )
    db.add(expense)

    await db.commit()
    return {"message": f"O'qituvchiga {req.amount:,.0f} so'm maosh to'landi va Xarajatlar kassasiga qayd etildi!"}


@router.get("/payroll", response_model=List[TeacherPayrollResponse])
async def list_teacher_payrolls(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    res = await db.execute(select(TeacherPayroll).order_by(TeacherPayroll.created_at.desc()))
    return res.scalars().all()


# ----------------------------------------------------
# 4. MONTHLY BILLING & RECURRING GENERATOR
# ----------------------------------------------------
async def execute_monthly_billing_and_notify(db: AsyncSession, target_month: Optional[str] = None) -> dict:
    """Yangi oy uchun barcha faol o'quvchilarga to'lov talabini shakllantirish va Telegramga xabar yuborish"""
    if not target_month:
        target_month = date.today().strftime("%Y-%m")

    groups_res = await db.execute(select(Group).where(Group.is_active == True))
    groups = groups_res.scalars().all()

    created_count = 0
    telegram_sent_count = 0

    for grp in groups:
        course_res = await db.execute(select(Course).where(Course.id == grp.course_id))
        course = course_res.scalar_one_or_none()
        if not course:
            continue

        st_res = await db.execute(
            select(GroupStudent).where(GroupStudent.group_id == grp.id, GroupStudent.is_active == True)
        )
        group_students = st_res.scalars().all()

        for gs in group_students:
            student_res = await db.execute(select(User).where(User.id == gs.student_id, User.is_active == True))
            student = student_res.scalar_one_or_none()
            if not student:
                continue

            exist_res = await db.execute(
                select(StudentBilling).where(
                    StudentBilling.student_id == gs.student_id,
                    StudentBilling.group_id == grp.id,
                    StudentBilling.month_for == target_month
                )
            )
            billing = exist_res.scalar_one_or_none()
            if not billing:
                billing = StudentBilling(
                    student_id=gs.student_id,
                    group_id=grp.id,
                    month_for=target_month,
                    amount_due=course.price_monthly,
                    amount_paid=0.0,
                    is_paid=False,
                    due_date=date.today()
                )
                db.add(billing)
                created_count += 1

                # Telegram xabar yuborish
                if student.telegram_chat_id:
                    msg = (
                        f"🔔 <b>YANGI OY UCHUN TO'LOV BILDIRISHNOMASI</b> 📅\n\n"
                        f"Assalomu alaykum, <b>{student.full_name}</b>!\n"
                        f"<b>{target_month}</b> oyi uchun to'lov hisob-kitobi shakllantirildi:\n\n"
                        f"📚 Kurs: <b>{course.title}</b> ({grp.name})\n"
                        f"💵 Oylik to'lov summasi: <b>{course.price_monthly:,.0f} so'm</b>\n\n"
                        f"⚠️ <i>Iltimos, darslar uzluksizligi uchun to'lovni oyning 5-sanasiga qadar amalga oshiring.</i>"
                    )
                    sent = await send_telegram_notification(student.telegram_chat_id, msg)
                    if sent:
                        telegram_sent_count += 1

    await db.commit()
    return {
        "month_for": target_month,
        "created_billings_count": created_count,
        "telegram_notifications_sent": telegram_sent_count,
        "message": f"{target_month} oyi uchun {created_count} ta to'lov hisobi yangilandi va {telegram_sent_count} ta Telegram xabarnoma yuborildi!"
    }


@router.post("/billing/generate")
async def generate_monthly_billing(
    req: StudentBillingGenerateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    result = await execute_monthly_billing_and_notify(db, req.month_for)
    return result


@router.post("/billing/auto-run")
async def auto_run_monthly_billing(
    month_for: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """Har oyning 1-sanasida avtomatik ishga tushuvchi yoki Admin tomonidan qo'lda sinovdan o'tkaziluvchi oylik to'lov yangilash"""
    result = await execute_monthly_billing_and_notify(db, month_for)
    return result


@router.get("/debtors", response_model=List[DebtorResponse])
async def list_debtors(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """Qarzdor o'quvchilar ro'yxatini va ularning qarzdorlik summasini olish"""
    stmt = select(User).where(User.role == UserRole.STUDENT, User.is_active == True)
    res = await db.execute(stmt)
    students = res.scalars().all()

    debtors = []
    for student in students:
        billings_res = await db.execute(
            select(StudentBilling).where(
                StudentBilling.student_id == student.id
            )
        )
        all_billings = billings_res.scalars().all()

        unpaid_billings = []
        for b in all_billings:
            pay_res = await db.execute(
                select(func.sum(Payment.amount)).where(
                    Payment.student_id == student.id,
                    Payment.month_for == b.month_for
                )
            )
            actual_paid = pay_res.scalar() or 0.0
            b.amount_paid = actual_paid
            b.is_paid = (actual_paid >= b.amount_due and b.amount_due > 0)
            if not b.is_paid:
                unpaid_billings.append(b)

        if unpaid_billings:
            total_debt = sum(b.amount_due - b.amount_paid for b in unpaid_billings)
            unpaid_months = list(dict.fromkeys(b.month_for for b in unpaid_billings))
            if total_debt > 0:
                debtors.append(
                    DebtorResponse(
                        student_id=student.id,
                        student_name=student.full_name,
                        phone=student.phone,
                        login_id=student.login_id,
                        total_debt=total_debt,
                        unpaid_months=unpaid_months
                    )
                )

    await db.commit()
    return debtors


@router.get("/dashboard-stats")
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    inc_res = await db.execute(select(func.sum(Payment.amount)))
    total_income = inc_res.scalar() or 0.0

    exp_res = await db.execute(select(func.sum(Expense.amount)))
    total_expense = exp_res.scalar() or 0.0

    std_res = await db.execute(select(func.count(User.id)).where(User.role == UserRole.STUDENT, User.is_active == True))
    total_students = std_res.scalar() or 0

    tch_res = await db.execute(select(func.count(User.id)).where(User.role == UserRole.TEACHER, User.is_active == True))
    total_teachers = tch_res.scalar() or 0

    return {
        "total_income": total_income,
        "total_expense": total_expense,
        "net_profit": total_income - total_expense,
        "active_students": total_students,
        "active_teachers": total_teachers
    }


@router.get("/invoices/", response_model=List[InvoiceResponse])
async def get_invoices(db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin)):
    result = await db.execute(select(Invoice))
    return result.scalars().all()


@router.post("/invoices/", response_model=InvoiceResponse)
async def create_invoice(invoice_in: InvoiceCreate, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin)):
    new_invoice = Invoice(**invoice_in.model_dump())
    db.add(new_invoice)
    await db.commit()
    await db.refresh(new_invoice)
    return new_invoice


@router.get("/payments/{payment_id}/pdf")
async def get_payment_receipt_pdf(
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    res = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = res.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="To'lov topilmadi!")

    std_res = await db.execute(select(User).where(User.id == payment.student_id))
    student = std_res.scalar_one_or_none()
    student_name = student.full_name if student else "Noma'lum Student"
    student_id_code = student.login_id if student else "N/A"

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica-Bold", 18)
    p.drawString(100, 750, "Ta'lim Plus O'quv Markazi — TO'LOV CHEKI")
    
    p.setFont("Helvetica", 12)
    p.drawString(100, 710, f"Chek ID: #{payment.id}")
    p.drawString(100, 690, f"Sana: {payment.created_at.strftime('%Y-%m-%d %H:%M')}")
    p.drawString(100, 660, f"O'quvchi: {student_name} (ID: {student_id_code})")
    p.drawString(100, 640, f"Summa: {payment.amount:,.0f} so'm")
    p.drawString(100, 620, f"To'lov turi: {payment.payment_method}")
    p.drawString(100, 600, f"Oy uchun: {payment.month_for}")
    if payment.note:
        p.drawString(100, 580, f"Izoh: {payment.note}")

    p.drawString(100, 520, "--------------------------------------------------------")
    p.setFont("Helvetica-Oblique", 10)
    p.drawString(100, 500, "To'lovingiz uchun rahmat! Ta'lim Plus jamoasi.")
    
    p.showPage()
    p.save()
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=receipt_{payment_id}.pdf"}
    )


@router.post("/calculate-proration")
async def calculate_proration(
    monthly_fee: float,
    total_lessons: int = 12,
    remaining_lessons: int = 6
):
    if total_lessons <= 0 or remaining_lessons <= 0:
        return {"calculated_fee": monthly_fee, "discount": 0.0}
    
    per_lesson_fee = monthly_fee / total_lessons
    calculated_fee = round(per_lesson_fee * remaining_lessons, -2)
    discount = monthly_fee - calculated_fee
    return {
        "monthly_fee": monthly_fee,
        "total_lessons": total_lessons,
        "remaining_lessons": remaining_lessons,
        "calculated_fee": calculated_fee,
        "discount": discount
    }

