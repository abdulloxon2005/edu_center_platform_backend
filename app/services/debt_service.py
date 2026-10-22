"""
Student Debt & Billing Service
Yagona qarzdorlik va oylik hisob-kitob xizmati.

Qoidalar:
1. Qarzdorlik FAQAT 1 oylik hisoblanadi (joriy yoki tanlangan oy uchun).
2. Hisob FAQAT 2026-yil oktabrdan (2026-10) boshlanadi. Oktabrdan oldingi davrlar (2026-09, 2026-08, ...)
   qarzdorlikka kirmaydi (qarz = 0).
3. Oktabrdan oldin qo'shilgan o'quvchilarning eski davr qarzi yangi hisobga qo'shilmaydi.
4. Guruhdagi individual tariflar (GRANT_100, DISCOUNT_50, custom_price) hisobga olinadi.
5. Faqat faol guruhlar va faol a'zoliklar (is_active == True) to'lov talabini hosil qiladi.
"""

from datetime import date
from typing import Optional, List, Dict
from dataclasses import dataclass
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    User, UserRole, Group, GroupStudent, Course, Payment, StudentBilling
)

# Qarzdorlik hisoblash tizimining boshlanish sanasi
DEBT_SYSTEM_START_MONTH = "2026-10"


@dataclass
class StudentDebtResult:
    student_id: int
    month_for: str
    total_monthly_fee: float
    amount_paid: float
    debt: float
    credit: float
    is_paid: bool
    is_debtor: bool
    active_groups_count: int


def calculate_student_effective_fee(gs: GroupStudent, crs: Course) -> float:
    """O'quvchining guruhdagi individual tarifi yoki fan standart narxini hisoblash"""
    if gs.discount_type == "GRANT_100":
        return 0.0
    elif gs.discount_type == "DISCOUNT_50":
        price = float(crs.price_monthly or 0.0)
        return round(price * 0.5, -2)
    elif gs.custom_price is not None:
        return float(gs.custom_price)
    return float(crs.price_monthly or 0.0)


def is_month_before_debt_start(month_str: str) -> bool:
    """Berilgan oy (YYYY-MM) 2026-10 dan oldin ekanligini tekshiradi"""
    if not month_str:
        return False
    return month_str < DEBT_SYSTEM_START_MONTH


async def calculate_student_debt(
    db: AsyncSession,
    student_id: int,
    month_for: Optional[str] = None
) -> StudentDebtResult:
    """
    O'quvchining ko'rsatilgan oy bo'yicha qarzdorligini hisoblash.
    Qoidaga binoan:
    - Hisob-kitob FAQAT 1 oylik (ko'rsatilgan oy uchun).
    - Agar oy < '2026-10' bo'lsa, qarz qat'iyan 0.0 bo'ladi.
    """
    if not month_for:
        month_for = date.today().strftime("%Y-%m")

    # 1. O'quvchining faol guruhlarini olish
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

    total_monthly_fee = sum(
        calculate_student_effective_fee(gs, crs)
        for gs, _, crs in active_rows
    )
    active_groups_count = len(active_rows)

    # 2. Ushbu oy uchun amalga oshirilgan to'lovlar
    pay_res = await db.execute(
        select(func.sum(Payment.amount)).where(
            Payment.student_id == student_id,
            Payment.month_for == month_for
        )
    )
    amount_paid = float(pay_res.scalar() or 0.0)

    # 3. 2026-10 dan oldingi davrlar qarz keltirib chiqarmaydi
    if is_month_before_debt_start(month_for):
        credit = max(0.0, amount_paid - total_monthly_fee)
        return StudentDebtResult(
            student_id=student_id,
            month_for=month_for,
            total_monthly_fee=total_monthly_fee,
            amount_paid=amount_paid,
            debt=0.0,
            credit=credit,
            is_paid=True,
            is_debtor=False,
            active_groups_count=active_groups_count
        )

    # 4. 2026-10 va undan keyingi davrlar uchun 1 oylik aniq qarz
    debt = max(0.0, total_monthly_fee - amount_paid)
    credit = max(0.0, amount_paid - total_monthly_fee)
    is_paid = (amount_paid >= total_monthly_fee and total_monthly_fee > 0)
    is_debtor = (debt > 0)

    return StudentDebtResult(
        student_id=student_id,
        month_for=month_for,
        total_monthly_fee=total_monthly_fee,
        amount_paid=amount_paid,
        debt=debt,
        credit=credit,
        is_paid=is_paid,
        is_debtor=is_debtor,
        active_groups_count=active_groups_count
    )


async def calculate_batch_students_debt(
    db: AsyncSession,
    student_ids: List[int],
    month_for: Optional[str] = None
) -> Dict[int, StudentDebtResult]:
    """
    Bir nechta o'quvchilar uchun qarzdorlikni ommaviy (batch) hisoblash.
    N+1 so'rovlarni oldini oladi.
    """
    if not month_for:
        month_for = date.today().strftime("%Y-%m")

    if not student_ids:
        return {}

    # 1. Guruhlarni olish
    stmt = (
        select(GroupStudent, Group, Course)
        .join(Group, GroupStudent.group_id == Group.id)
        .join(Course, Group.course_id == Course.id)
        .where(
            GroupStudent.student_id.in_(student_ids),
            GroupStudent.is_active == True,
            Group.is_active == True
        )
    )
    res_groups = await db.execute(stmt)
    rows = res_groups.all()

    student_fees: Dict[int, float] = {sid: 0.0 for sid in student_ids}
    student_group_counts: Dict[int, int] = {sid: 0 for sid in student_ids}
    for gs, _, crs in rows:
        eff_fee = calculate_student_effective_fee(gs, crs)
        student_fees[gs.student_id] = student_fees.get(gs.student_id, 0.0) + eff_fee
        student_group_counts[gs.student_id] = student_group_counts.get(gs.student_id, 0) + 1

    # 2. To'lovlarni olish
    pay_stmt = (
        select(Payment.student_id, func.sum(Payment.amount))
        .where(
            Payment.student_id.in_(student_ids),
            Payment.month_for == month_for
        )
        .group_by(Payment.student_id)
    )
    pay_res = await db.execute(pay_stmt)
    pay_map: Dict[int, float] = {sid: float(amount or 0.0) for sid, amount in pay_res.all()}

    is_pre_october = is_month_before_debt_start(month_for)

    results: Dict[int, StudentDebtResult] = {}
    for sid in student_ids:
        fee = student_fees.get(sid, 0.0)
        paid = pay_map.get(sid, 0.0)
        cnt = student_group_counts.get(sid, 0)

        if is_pre_october:
            results[sid] = StudentDebtResult(
                student_id=sid,
                month_for=month_for,
                total_monthly_fee=fee,
                amount_paid=paid,
                debt=0.0,
                credit=max(0.0, paid - fee),
                is_paid=True,
                is_debtor=False,
                active_groups_count=cnt
            )
        else:
            debt = max(0.0, fee - paid)
            credit = max(0.0, paid - fee)
            is_paid = (paid >= fee and fee > 0)
            is_debtor = (debt > 0)
            results[sid] = StudentDebtResult(
                student_id=sid,
                month_for=month_for,
                total_monthly_fee=fee,
                amount_paid=paid,
                debt=debt,
                credit=credit,
                is_paid=is_paid,
                is_debtor=is_debtor,
                active_groups_count=cnt
            )

    return results


async def sync_student_billing_record(
    db: AsyncSession,
    student_id: int,
    month_for: str
) -> Optional[StudentBilling]:
    """
    O'quvchining ko'rsatilgan oy bo'yicha StudentBilling yozuvini sinxronlash.
    2026-10 dan oldingi davrlar uchun amount_due = 0.0 yoki is_paid = True qilinadi.
    """
    debt_info = await calculate_student_debt(db, student_id, month_for)

    # Faol guruh ID sini topish
    grp_stmt = (
        select(GroupStudent.group_id)
        .join(Group, GroupStudent.group_id == Group.id)
        .where(
            GroupStudent.student_id == student_id,
            GroupStudent.is_active == True,
            Group.is_active == True
        )
        .limit(1)
    )
    grp_res = await db.execute(grp_stmt)
    group_id = grp_res.scalar() or 1

    # Mavjud billing yozuvlari
    billing_res = await db.execute(
        select(StudentBilling).where(
            StudentBilling.student_id == student_id,
            StudentBilling.month_for == month_for
        )
    )
    billings = billing_res.scalars().all()

    due = debt_info.total_monthly_fee
    paid = debt_info.amount_paid
    is_paid = debt_info.is_paid

    # 2026-10 dan oldin qarz bo'lmasligi kerak
    if is_month_before_debt_start(month_for):
        is_paid = True

    if not billings:
        billing = StudentBilling(
            student_id=student_id,
            group_id=group_id,
            month_for=month_for,
            amount_due=due,
            amount_paid=paid,
            is_paid=is_paid,
            due_date=date.today()
        )
        db.add(billing)
        await db.flush()
        return billing
    else:
        primary = billings[0]
        primary.amount_due = due
        primary.amount_paid = paid
        primary.is_paid = is_paid
        for b in billings[1:]:
            b.amount_due = 0.0
            b.amount_paid = 0.0
            b.is_paid = is_paid
        await db.flush()
        return primary
