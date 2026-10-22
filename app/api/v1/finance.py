from datetime import date
from io import BytesIO
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
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
    PaymentCreate, PaymentResponse, PaymentUpdate, ExpenseCreate, ExpenseUpdate, ExpenseResponse,
    PayrollCalculateRequest, PayrollPayRequest, TeacherPayrollResponse,
    StudentBillingGenerateRequest, StudentBillingResponse, DebtorResponse,
    InvoiceCreate, InvoiceResponse, StudentBillingInfoResponse,
    StudentGroupCourseInfo, PaymentRecordResult
)
from app.api.deps import get_current_admin, get_current_user
from app.services.notification import send_telegram_notification
from app.core.formatters import format_month_uz, format_payment_method_uz
from app.services.debt_service import (
    calculate_student_effective_fee,
    calculate_student_debt,
    calculate_batch_students_debt,
    sync_student_billing_record,
    is_month_before_debt_start,
    DEBT_SYSTEM_START_MONTH
)

router = APIRouter()


async def sync_student_billing(db: AsyncSession, student_id: int, month_for: str) -> Optional[StudentBilling]:
    """O'quvchining ko'rsatilgan oy bo'yicha to'lovlari asosida StudentBilling yozuvini aniq sinxronizatsiya qilish"""
    return await sync_student_billing_record(db, student_id, month_for)



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

    # 2. O'quvchi biriktirilgan faol guruhlar va kurslar (tariflari bilan)
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
        eff_fee = calculate_student_effective_fee(gs, crs)
        groups_info.append(StudentGroupCourseInfo(
            group_id=grp.id,
            group_name=grp.name,
            course_id=crs.id,
            course_title=crs.title,
            price_monthly=crs.price_monthly,
            effective_fee=eff_fee,
            discount_type=gs.discount_type or "STANDARD",
            discount_note=gs.discount_note
        ))
        total_monthly_fee += eff_fee


    # 3. Tanlangan oy bo'yicha StudentBilling ni sinxronlashtirish va olish
    await sync_student_billing(db, student_id, month_for)
    await db.commit()

    debt_info = await calculate_student_debt(db, student_id, month_for)

    return StudentBillingInfoResponse(
        student_id=student.id,
        student_name=student.full_name,
        login_id=student.login_id,
        phone=student.phone,
        father_phone=student.father_phone,
        mother_phone=student.mother_phone,
        parent_phone=student.parent_phone,
        telegram_chat_id=student.telegram_chat_id,
        groups=groups_info,
        total_monthly_fee=debt_info.total_monthly_fee,
        month_for=month_for,
        month_amount_due=debt_info.total_monthly_fee,
        month_amount_paid=debt_info.amount_paid,
        month_remaining_due=debt_info.debt,
        month_surplus=debt_info.credit,
        past_debt=0.0,
        past_credit=0.0,
        total_debt=debt_info.debt,
        total_credit=debt_info.credit,
        net_balance=debt_info.credit - debt_info.debt
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
        debt_info = await calculate_student_debt(db, student.id, month_for)

        is_paid = debt_info.is_paid
        is_partial = 0 < debt_info.amount_paid < debt_info.total_monthly_fee

        result.append({
            "student_id": student.id,
            "full_name": student.full_name,
            "login_id": student.login_id,
            "phone": student.phone,
            "father_phone": student.father_phone,
            "mother_phone": student.mother_phone,
            "parent_phone": student.parent_phone,
            "month_for": month_for,
            "expected_fee": debt_info.total_monthly_fee,
            "amount_paid": debt_info.amount_paid,
            "remaining_due": debt_info.debt,
            "is_paid": is_paid,
            "is_partial": is_partial,
            "total_debt": debt_info.debt,
            "total_credit": debt_info.credit,
            "net_balance": debt_info.credit - debt_info.debt,
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
    total_monthly_fee = sum(calculate_student_effective_fee(gs, crs) for gs, _, crs in active_rows)
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
        f"📅 To'lov oyi: <b>{format_month_uz(payment.month_for)}</b>\n"
        f"💳 To'lov turi: <b>{format_payment_method_uz(payment.payment_method)}</b>\n"
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
    search: Optional[str] = None,
    month_for: Optional[str] = None,
    payment_method: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    stmt = (
        select(Payment, User.full_name, User.login_id)
        .outerjoin(User, Payment.student_id == User.id)
    )
    if month_for:
        stmt = stmt.where(Payment.month_for == month_for)
    if payment_method:
        stmt = stmt.where(Payment.payment_method == payment_method)
    if search and search.strip():
        term = f"%{search.strip()}%"
        stmt = stmt.where(
            (User.full_name.ilike(term)) |
            (User.login_id.ilike(term)) |
            (Payment.note.ilike(term)) |
            (Payment.month_for.ilike(term))
        )
    stmt = stmt.order_by(Payment.created_at.desc())
    res = await db.execute(stmt)
    rows = res.all()

    payment_responses = []
    for p, full_name, login_id in rows:
        resp = PaymentResponse.model_validate(p)
        resp.student_name = full_name or "Noma'lum"
        resp.student_login_id = login_id or ""
        payment_responses.append(resp)
    return payment_responses


@router.get("/student/{student_id}/payments", response_model=List[PaymentResponse])
async def get_student_payments(
    student_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stmt = (
        select(Payment, User.full_name, User.login_id)
        .outerjoin(User, Payment.student_id == User.id)
        .where(Payment.student_id == student_id)
        .order_by(Payment.created_at.desc())
    )
    res = await db.execute(stmt)
    rows = res.all()
    results = []
    for p, full_name, login_id in rows:
        resp = PaymentResponse.model_validate(p)
        resp.student_name = full_name or ""
        resp.student_login_id = login_id or ""
        results.append(resp)
    return results


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

    emp_name = None
    if expense.employee_id:
        u_res = await db.execute(select(User.full_name).where(User.id == expense.employee_id))
        emp_name = u_res.scalar_one_or_none()

    return ExpenseResponse(
        id=expense.id,
        title=expense.title,
        amount=expense.amount,
        category=expense.category,
        date=expense.date,
        description=expense.description,
        employee_id=expense.employee_id,
        employee_name=emp_name,
        payment_method=expense.payment_method or "CASH",
        created_at=expense.created_at
    )


@router.get("/expenses", response_model=List[ExpenseResponse])
async def list_expenses(
    employee_id: Optional[int] = None,
    payment_method: Optional[str] = None,
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    stmt = (
        select(Expense, User.full_name.label("employee_name"))
        .outerjoin(User, Expense.employee_id == User.id)
        .order_by(Expense.date.desc(), Expense.id.desc())
    )
    if employee_id:
        stmt = stmt.where(Expense.employee_id == employee_id)
    if payment_method and payment_method != "ALL":
        stmt = stmt.where(Expense.payment_method == payment_method)
    if category and category != "ALL":
        stmt = stmt.where(Expense.category == category)

    res = await db.execute(stmt)
    results = []
    for exp, emp_name in res.all():
        results.append(ExpenseResponse(
            id=exp.id,
            title=exp.title,
            amount=exp.amount,
            category=exp.category,
            date=exp.date,
            description=exp.description,
            employee_id=exp.employee_id,
            employee_name=emp_name,
            payment_method=exp.payment_method or "CASH",
            created_at=exp.created_at
        ))
    return results


@router.put("/expenses/{expense_id}", response_model=ExpenseResponse)
async def update_expense(
    expense_id: int,
    expense_in: ExpenseUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    res = await db.execute(select(Expense).where(Expense.id == expense_id))
    expense = res.scalar_one_or_none()
    if not expense:
        raise HTTPException(status_code=404, detail="Xarajat topilmadi!")

    for key, value in expense_in.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(expense, key, value)

    await db.commit()
    await db.refresh(expense)

    emp_name = None
    if expense.employee_id:
        u_res = await db.execute(select(User.full_name).where(User.id == expense.employee_id))
        emp_name = u_res.scalar_one_or_none()

    return ExpenseResponse(
        id=expense.id,
        title=expense.title,
        amount=expense.amount,
        category=expense.category,
        date=expense.date,
        description=expense.description,
        employee_id=expense.employee_id,
        employee_name=emp_name,
        payment_method=expense.payment_method or "CASH",
        created_at=expense.created_at
    )


@router.delete("/expenses/{expense_id}")
async def delete_expense(
    expense_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    res = await db.execute(select(Expense).where(Expense.id == expense_id))
    expense = res.scalar_one_or_none()
    if not expense:
        raise HTTPException(status_code=404, detail="Xarajat topilmadi!")

    await db.delete(expense)
    await db.commit()
    return {"message": "Xarajat muvaffaqiyatli o'chirildi!"}


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

    if is_month_before_debt_start(target_month):
        return {
            "month_for": target_month,
            "created_billings_count": 0,
            "telegram_notifications_sent": 0,
            "message": f"{target_month} oyi {DEBT_SYSTEM_START_MONTH} dan oldin bo'lgani uchun qarzdorlik hisoblanmaydi."
        }

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
                effective_fee = calculate_student_effective_fee(gs, course)
                billing = StudentBilling(
                    student_id=gs.student_id,
                    group_id=grp.id,
                    month_for=target_month,
                    amount_due=effective_fee,
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
                        f"<b>{format_month_uz(target_month)}</b> oyi uchun to'lov hisob-kitobi shakllantirildi:\n\n"
                        f"📚 Kurs: <b>{course.title}</b> ({grp.name})\n"
                        f"💵 Oylik to'lov summasi: <b>{effective_fee:,.0f} so'm</b>\n\n"
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
    month_for: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """Qarzdor o'quvchilar ro'yxatini va ularning qarzdorlik summasini olish (faqat 1 oylik va 2026-10 dan boshlab)"""
    if not month_for:
        month_for = date.today().strftime("%Y-%m")

    # 2026-10 dan oldingi davrlar uchun qarzdorlik hisoblanmaydi
    if is_month_before_debt_start(month_for):
        return []

    stmt = select(User).where(User.role == UserRole.STUDENT, User.is_active == True)
    res = await db.execute(stmt)
    students = res.scalars().all()
    if not students:
        return []

    debt_map = await calculate_batch_students_debt(db, [s.id for s in students], month_for)

    debtors = []
    for s in students:
        d_res = debt_map.get(s.id)
        if d_res and d_res.debt > 0:
            debtors.append(
                DebtorResponse(
                    student_id=s.id,
                    student_name=s.full_name,
                    phone=s.phone,
                    father_phone=s.father_phone,
                    mother_phone=s.mother_phone,
                    parent_phone=s.parent_phone,
                    login_id=s.login_id,
                    total_debt=d_res.debt,
                    unpaid_months=[month_for]
                )
            )

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
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = res.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="To'lov topilmadi!")

    std_res = await db.execute(select(User).where(User.id == payment.student_id))
    student = std_res.scalar_one_or_none()
    student_name = student.full_name if student else "Noma'lum Student"
    student_id_code = student.login_id if student else "N/A"
    student_phone = student.phone or student.parent_phone or "Mavjud emas"

    # Guruh ma'lumotlarini aniqlash (o'quvchining faol guruhlari)
    grp_res = await db.execute(
        select(Group.name)
        .join(GroupStudent, GroupStudent.group_id == Group.id)
        .where(GroupStudent.student_id == payment.student_id, GroupStudent.is_active == True)
    )
    group_names = grp_res.scalars().all()
    group_name = ", ".join(group_names) if group_names else "Umumiy ta'lim to'lovi"

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    
    # Header dekoratsiya
    p.setFillColorRGB(0.145, 0.388, 0.921) # #2563eb
    p.rect(50, 720, 512, 60, fill=True, stroke=False)
    
    p.setFillColorRGB(1, 1, 1)
    p.setFont("Helvetica-Bold", 18)
    p.drawString(70, 752, "Ta'lim Plus Education Center")
    p.setFont("Helvetica", 11)
    p.drawString(70, 735, "RASMIY TO'LOV CHEKI (PAYMENT RECEIPT)")

    # Asosiy ramka
    p.setStrokeColorRGB(0.796, 0.859, 0.968) # #bfdbfe
    p.setLineWidth(1)
    p.rect(50, 240, 512, 460)

    # Chek ma'lumotlari
    p.setFillColorRGB(0.058, 0.090, 0.164) # #0f172a
    p.setFont("Helvetica-Bold", 14)
    p.drawString(70, 670, f"Chek raqami: #{payment.id}")
    
    p.setFont("Helvetica", 10)
    p.setFillColorRGB(0.392, 0.455, 0.545) # #64748b
    p.drawString(70, 652, f"Sana va vaqt: {payment.created_at.strftime('%Y-%m-%d %H:%M:%S')}")

    # Chiziq
    p.setStrokeColorRGB(0.886, 0.909, 0.941) # #e2e8f0
    p.line(70, 638, 542, 638)

    # Tafsilotlar
    details = [
        ("O'quvchi F.I.Sh:", f"{student_name}"),
        ("Login ID raqami:", f"{student_id_code}"),
        ("Telefon raqami:", f"{student_phone}"),
        ("Guruh / Kurs:", f"{group_name}"),
        ("To'lov oyi:", f"{format_month_uz(payment.month_for)}"),
        ("To'lov usuli:", f"{format_payment_method_uz(payment.payment_method)}"),
        ("Holat:", "Muvaffaqiyatli qabul qilindi (TASDIQLANGAN)"),
    ]

    y = 610
    for label, val in details:
        p.setFont("Helvetica-Bold", 10)
        p.setFillColorRGB(0.278, 0.333, 0.412)
        p.drawString(70, y, label)
        
        p.setFont("Helvetica", 10)
        p.setFillColorRGB(0.058, 0.090, 0.164)
        p.drawString(200, y, str(val))
        y -= 26

    if payment.note:
        p.setFont("Helvetica-Bold", 10)
        p.setFillColorRGB(0.278, 0.333, 0.412)
        p.drawString(70, y, "Izoh:")
        p.setFont("Helvetica-Oblique", 10)
        p.setFillColorRGB(0.058, 0.090, 0.164)
        p.drawString(200, y, payment.note[:50])
        y -= 26

    # Summa bloki (ajratilgan yorqin karta)
    p.setFillColorRGB(0.937, 0.965, 1.0) # #eff6ff
    p.rect(70, y - 45, 472, 45, fill=True, stroke=False)
    p.setFillColorRGB(0.114, 0.306, 0.847)
    p.setFont("Helvetica-Bold", 12)
    p.drawString(85, y - 28, "JAMI TO'LANGAN SUMMA:")
    p.setFont("Helvetica-Bold", 16)
    p.drawString(340, y - 29, f"{payment.amount:,.0f} UZS")

    # Pastki qism
    p.setFont("Helvetica-Oblique", 9)
    p.setFillColorRGB(0.392, 0.455, 0.545)
    p.drawString(70, 275, "Ushbu to'lov cheki elektron tizim orqali avtomatik shakllantirilgan.")
    p.drawString(70, 260, "Ta'lim Plus Education Center - Kelajagingiz biz bilan ishonchli qo'llarda!")
    p.drawString(70, 246, "Platforma ishlab chiquvchisi: Roziyev Systems")

    p.showPage()
    p.save()
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=receipt_{payment_id}.pdf"}
    )


@router.post("/calculate-proration")
async def calculate_proration(
    monthly_fee: float,
    total_lessons: int = 12,
    remaining_lessons: int = 6,
    discount_type: Optional[str] = "STANDARD",
    custom_discount_amount: Optional[float] = 0.0
):
    if discount_type == "GRANT_100":
        return {
            "monthly_fee": monthly_fee,
            "total_lessons": total_lessons,
            "remaining_lessons": remaining_lessons,
            "calculated_fee": 0.0,
            "discount": monthly_fee,
            "tariff_name": "100% Grant (To'liq Imtiyozli)"
        }
    elif discount_type == "DISCOUNT_50":
        calc = round(monthly_fee * 0.5, -2)
        return {
            "monthly_fee": monthly_fee,
            "total_lessons": total_lessons,
            "remaining_lessons": remaining_lessons,
            "calculated_fee": calc,
            "discount": monthly_fee - calc,
            "tariff_name": "50% Chegirma (Yarim Imtiyozli)"
        }

    if total_lessons <= 0:
        total_lessons = 12
    if remaining_lessons <= 0:
        remaining_lessons = total_lessons

    per_lesson_fee = monthly_fee / total_lessons
    base_calc = round(per_lesson_fee * remaining_lessons, -2)
    final_fee = max(0.0, base_calc - (custom_discount_amount or 0.0))
    discount = monthly_fee - final_fee

    return {
        "monthly_fee": monthly_fee,
        "total_lessons": total_lessons,
        "remaining_lessons": remaining_lessons,
        "calculated_fee": final_fee,
        "discount": discount,
        "tariff_name": "Pro-rata / Standart hisob-kitob"
    }


