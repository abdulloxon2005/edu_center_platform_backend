"""
Telegram Bot uchun maxsus API endpointlar.
JWT talab qilinmaydi — chat_id orqali identifikatsiya.
Xavfsizlik: Har bir endpoint chat_id ga bog'langan o'quvchilarni tekshiradi.
"""
from datetime import date
from typing import List
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.core.database import get_db
from app.models.models import (
    User, UserRole, ParentStudent, GroupStudent, Group, Course,
    Payment, StudentBilling, Lesson, Attendance, AttendanceStatus
)
from app.schemas.schemas import (
    TelegramStudentInfo, TelegramPaymentHistory, TelegramPaymentItem,
    TelegramAttendanceStats
)

router = APIRouter()


async def get_linked_student_ids(db: AsyncSession, chat_id: str) -> list[int]:
    """
    Chat ID ga bog'langan barcha o'quvchi ID larini qaytaradi.
    1. User.telegram_chat_id == chat_id bo'lgan o'quvchilar (to'g'ridan-to'g'ri bog'langan)
    2. ParentStudent orqali: ota-ona User.telegram_chat_id == chat_id bo'lsa, uning farzandlari
    """
    student_ids = set()

    # 1. To'g'ridan-to'g'ri bog'langan o'quvchilar
    direct_res = await db.execute(
        select(User.id).where(
            User.telegram_chat_id == chat_id,
            User.role == UserRole.STUDENT,
            User.is_active == True
        )
    )
    for row in direct_res.scalars().all():
        student_ids.add(row)

    # 2. ParentStudent orqali — ota-ona chatiga bog'langan farzandlar
    parent_res = await db.execute(
        select(User.id).where(
            User.telegram_chat_id == chat_id,
            User.role == UserRole.PARENT,
            User.is_active == True
        )
    )
    parent_ids = parent_res.scalars().all()

    if parent_ids:
        children_res = await db.execute(
            select(ParentStudent.student_id).where(
                ParentStudent.parent_id.in_(parent_ids)
            )
        )
        for row in children_res.scalars().all():
            student_ids.add(row)

    # 3. Har qanday roldagi user telegram_chat_id == chat_id bo'lsa
    #    va ParentStudent jadvalida parent sifatida bog'langan bo'lsa
    any_user_res = await db.execute(
        select(User.id).where(
            User.telegram_chat_id == chat_id,
            User.is_active == True
        )
    )
    any_user_ids = any_user_res.scalars().all()
    if any_user_ids:
        more_children_res = await db.execute(
            select(ParentStudent.student_id).where(
                ParentStudent.parent_id.in_(any_user_ids)
            )
        )
        for row in more_children_res.scalars().all():
            student_ids.add(row)

    return list(student_ids)


async def verify_student_access(db: AsyncSession, chat_id: str, student_id: int) -> bool:
    """Chat ID ning ushbu student_id ga kirish huquqi borligini tekshiradi"""
    linked_ids = await get_linked_student_ids(db, chat_id)
    return student_id in linked_ids


# ============================================================
# 1. Bog'langan o'quvchilar ro'yxati
# ============================================================
@router.get("/students", response_model=List[TelegramStudentInfo])
async def get_linked_students(
    chat_id: str = Query(..., description="Telegram chat ID"),
    db: AsyncSession = Depends(get_db)
):
    """Chat ID ga bog'langan barcha o'quvchilar ro'yxatini qaytaradi"""
    student_ids = await get_linked_student_ids(db, chat_id)

    if not student_ids:
        raise HTTPException(
            status_code=404,
            detail="Bu Telegram chatga hech qanday o'quvchi bog'lanmagan. Avval farzandingizning 6 talik ID raqamini kiriting."
        )

    result = []
    for sid in student_ids:
        # O'quvchi ma'lumotlari
        user_res = await db.execute(select(User).where(User.id == sid))
        student = user_res.scalar_one_or_none()
        if not student:
            continue

        # Guruh va kurs ma'lumotlari
        group_res = await db.execute(
            select(GroupStudent, Group, Course)
            .join(Group, GroupStudent.group_id == Group.id)
            .join(Course, Group.course_id == Course.id)
            .where(
                GroupStudent.student_id == sid,
                GroupStudent.is_active == True,
                Group.is_active == True
            )
        )
        group_row = group_res.first()

        result.append(TelegramStudentInfo(
            student_id=student.id,
            full_name=student.full_name,
            login_id=student.login_id,
            phone=student.phone,
            group_name=group_row[1].name if group_row else None,
            course_title=group_row[2].title if group_row else None,
            days_of_week=group_row[1].days_of_week if group_row else None,
            start_time=group_row[1].start_time if group_row else None,
            student_status=student.student_status.value if student.student_status else None
        ))

    return result


# ============================================================
# 2. To'lov tarixi va holati
# ============================================================
@router.get("/payments/{student_id}", response_model=TelegramPaymentHistory)
async def get_student_payments(
    student_id: int,
    chat_id: str = Query(..., description="Telegram chat ID"),
    db: AsyncSession = Depends(get_db)
):
    """O'quvchining to'lov tarixi va joriy oy holati"""
    # Xavfsizlik tekshiruvi
    if not await verify_student_access(db, chat_id, student_id):
        raise HTTPException(status_code=403, detail="Ushbu o'quvchi ma'lumotlariga kirish huquqi yo'q!")

    # O'quvchi ma'lumotlari
    st_res = await db.execute(select(User).where(User.id == student_id))
    student = st_res.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="O'quvchi topilmadi!")

    current_month = date.today().strftime("%Y-%m")

    # Oylik to'lov summasi (kurslar bo'yicha)
    group_res = await db.execute(
        select(GroupStudent, Group, Course)
        .join(Group, GroupStudent.group_id == Group.id)
        .join(Course, Group.course_id == Course.id)
        .where(
            GroupStudent.student_id == student_id,
            GroupStudent.is_active == True,
            Group.is_active == True
        )
    )
    rows = group_res.all()
    monthly_fee = sum(c.price_monthly for _, _, c in rows)

    # Joriy oy to'langan summa
    month_pay_res = await db.execute(
        select(func.sum(Payment.amount)).where(
            Payment.student_id == student_id,
            Payment.month_for == current_month
        )
    )
    month_paid = month_pay_res.scalar() or 0.0

    # Joriy oy billing
    billing_res = await db.execute(
        select(StudentBilling).where(
            StudentBilling.student_id == student_id,
            StudentBilling.month_for == current_month
        )
    )
    billings = billing_res.scalars().all()
    month_due = sum(b.amount_due for b in billings) if billings else monthly_fee
    remaining = max(0.0, month_due - month_paid)
    is_paid = month_paid >= month_due and month_due > 0

    # Umumiy qarz / haqdorlik
    all_billings_res = await db.execute(
        select(func.sum(StudentBilling.amount_due)).where(
            StudentBilling.student_id == student_id
        )
    )
    total_due_val = all_billings_res.scalar()
    total_due = total_due_val if total_due_val is not None else monthly_fee

    all_payments_res = await db.execute(
        select(func.sum(Payment.amount)).where(
            Payment.student_id == student_id
        )
    )
    total_paid = all_payments_res.scalar() or 0.0
    net = total_paid - total_due
    total_debt = abs(net) if net < 0 else 0.0
    total_credit = net if net > 0 else 0.0

    # Oxirgi 10 ta to'lov
    payments_res = await db.execute(
        select(Payment)
        .where(Payment.student_id == student_id)
        .order_by(Payment.created_at.desc())
        .limit(10)
    )
    recent_payments = [
        TelegramPaymentItem(
            id=p.id,
            amount=p.amount,
            payment_method=p.payment_method.value,
            month_for=p.month_for,
            created_at=p.created_at,
            note=p.note
        )
        for p in payments_res.scalars().all()
    ]

    return TelegramPaymentHistory(
        student_id=student.id,
        student_name=student.full_name,
        login_id=student.login_id,
        current_month=current_month,
        monthly_fee=monthly_fee,
        month_amount_paid=month_paid,
        month_amount_due=month_due,
        remaining=remaining,
        is_paid=is_paid,
        total_debt=total_debt,
        total_credit=total_credit,
        recent_payments=recent_payments
    )


# ============================================================
# 3. Davomat statistikasi
# ============================================================
@router.get("/attendance/{student_id}", response_model=TelegramAttendanceStats)
async def get_student_attendance(
    student_id: int,
    chat_id: str = Query(..., description="Telegram chat ID"),
    db: AsyncSession = Depends(get_db)
):
    """O'quvchining davomat statistikasi — joriy oy va umumiy"""
    # Xavfsizlik tekshiruvi
    if not await verify_student_access(db, chat_id, student_id):
        raise HTTPException(status_code=403, detail="Ushbu o'quvchi ma'lumotlariga kirish huquqi yo'q!")

    # O'quvchi
    st_res = await db.execute(select(User).where(User.id == student_id))
    student = st_res.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="O'quvchi topilmadi!")

    current_month = date.today().strftime("%Y-%m")
    month_start = date.today().replace(day=1)

    # Guruh ma'lumotlari
    group_res = await db.execute(
        select(GroupStudent, Group, Course)
        .join(Group, GroupStudent.group_id == Group.id)
        .join(Course, Group.course_id == Course.id)
        .where(
            GroupStudent.student_id == student_id,
            GroupStudent.is_active == True,
            Group.is_active == True
        )
    )
    group_row = group_res.first()

    group_name = group_row[1].name if group_row else None
    course_title = group_row[2].title if group_row else None
    days_of_week = group_row[1].days_of_week if group_row else None

    # Joriy oy davomat statistikasi
    month_stats_res = await db.execute(
        select(Attendance.status, func.count(Attendance.id))
        .join(Lesson, Attendance.lesson_id == Lesson.id)
        .where(
            Attendance.student_id == student_id,
            Lesson.lesson_date >= month_start
        )
        .group_by(Attendance.status)
    )
    month_stats = {row[0]: row[1] for row in month_stats_res.all()}

    month_present = month_stats.get(AttendanceStatus.PRESENT, 0)
    month_late = month_stats.get(AttendanceStatus.LATE, 0)
    month_absent = month_stats.get(AttendanceStatus.ABSENT, 0)
    month_excused = month_stats.get(AttendanceStatus.EXCUSED, 0)
    month_total = month_present + month_late + month_absent + month_excused

    # Umumiy davomat statistikasi
    overall_stats_res = await db.execute(
        select(Attendance.status, func.count(Attendance.id))
        .where(Attendance.student_id == student_id)
        .group_by(Attendance.status)
    )
    overall_stats = {row[0]: row[1] for row in overall_stats_res.all()}

    overall_present = overall_stats.get(AttendanceStatus.PRESENT, 0)
    overall_late = overall_stats.get(AttendanceStatus.LATE, 0)
    overall_absent = overall_stats.get(AttendanceStatus.ABSENT, 0)
    overall_excused = overall_stats.get(AttendanceStatus.EXCUSED, 0)
    overall_total = overall_present + overall_late + overall_absent + overall_excused

    return TelegramAttendanceStats(
        student_id=student.id,
        student_name=student.full_name,
        login_id=student.login_id,
        group_name=group_name,
        course_title=course_title,
        days_of_week=days_of_week,
        current_month=current_month,
        month_total=month_total,
        month_present=month_present,
        month_late=month_late,
        month_absent=month_absent,
        month_excused=month_excused,
        overall_total=overall_total,
        overall_present=overall_present,
        overall_late=overall_late,
        overall_absent=overall_absent,
        overall_excused=overall_excused
    )
