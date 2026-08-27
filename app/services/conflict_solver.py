from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.models import Group
from fastapi import HTTPException, status

def check_time_overlap(start1: str, end1: str, start2: str, end2: str) -> bool:
    """Tekshiradi: ikkita vaqt oralig'i bir-birini kesshadimi (masalan 14:00-16:00 va 15:00-17:00)"""
    return not (end1 <= start2 or end2 <= start1)

def check_days_overlap(days1_str: str, days2_str: str) -> bool:
    """Tekshiradi: ikkita kunlar ro'yxatida kamida 1 ta bir xil kun bormi"""
    set1 = set([d.strip().upper() for d in days1_str.split(",") if d.strip()])
    set2 = set([d.strip().upper() for d in days2_str.split(",") if d.strip()])
    return bool(set1.intersection(set2))

async def validate_group_schedule(
    db: AsyncSession,
    teacher_id: int,
    room_id: int,
    days_of_week: str,
    start_time: str,
    end_time: str,
    exclude_group_id: int = None
):
    """
    Dars jadvalida Xona va O'qituvchi bandligini tekshirish algoritmi.
    Konflikt topilsa HTTPException (400) qaytaradi.
    """
    # 1. Barcha faol guruhlarni olish
    stmt = select(Group).where(Group.is_active == True)
    if exclude_group_id:
        stmt = stmt.where(Group.id != exclude_group_id)
        
    result = await db.execute(stmt)
    active_groups = result.scalars().all()

    for grp in active_groups:
        # Agar haftaning kunlari va vaqtlari mos kelsa
        if check_days_overlap(days_of_week, grp.days_of_week) and check_time_overlap(start_time, end_time, grp.start_time, grp.end_time):
            # Xona konflikti
            if grp.room_id == room_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"DARS JADVALI KONFLIKTI: '{grp.name}' guruhi ko'rsatilgan xonada ({start_time}-{end_time}) dars o'tadi!"
                )
            # O'qituvchi konflikti
            if grp.teacher_id == teacher_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"O'QITUVCHI KONFLIKTI: Ushbu o'qituvchi tayinlangan vaqtda ({start_time}-{end_time}) boshqa guruhda darsi bor!"
                )
    return True
