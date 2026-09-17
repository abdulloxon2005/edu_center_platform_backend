import random
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.security import get_password_hash
from app.models.models import (
    User, UserRole, StudentStatusEnum, StudentFreeze, GroupTransferLog,
    ParentStudent, TelegramNotificationLog, GroupStudent, CoinTransaction
)
from app.schemas.schemas import (
    UserCreate, UserUpdate, UserResponse,
    StudentFreezeCreate, StudentFreezeResponse,
    GroupTransferLogCreate, GroupTransferLogResponse,
    ParentStudentCreate, ParentStudentResponse,
    TelegramNotificationLogResponse
)
from app.api.deps import get_current_admin, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_LOGIN_ID_ATTEMPTS = 100

async def generate_unique_login_id(db: AsyncSession) -> str:
    """Avtomatik unikal 6 talik raqamli login_id generatsiyasi"""
    for _ in range(MAX_LOGIN_ID_ATTEMPTS):
        candidate = str(random.randint(100000, 999999))
        stmt = select(User).where(User.login_id == candidate)
        res = await db.execute(stmt)
        if not res.scalar_one_or_none():
            return candidate
    raise HTTPException(status_code=500, detail="Unikal login ID generatsiya qilib bo'lmadi. Qaytadan urinib ko'ring!")

@router.post("/", response_model=UserResponse)
async def create_user(
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    stmt = select(User).where(User.phone == user_in.phone)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Ushbu telefon raqamiga ega foydalanuvchi allaqachon mavjud!")

    login_id = user_in.login_id or await generate_unique_login_id(db)
    temp_password = user_in.password or "123456"

    db_user = User(
        login_id=login_id,
        full_name=user_in.full_name,
        phone=user_in.phone,
        parent_phone=user_in.parent_phone,
        hashed_password=get_password_hash(temp_password),
        is_password_changed=False,
        role=user_in.role,
        telegram_chat_id=user_in.telegram_chat_id
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    logger.info(f"Yangi foydalanuvchi yaratildi: {db_user.login_id} ({db_user.role})")
    return db_user

from app.models.models import User, UserRole, StudentFreeze, GroupTransferLog, ParentStudent, TelegramNotificationLog, GroupStudent, CoinTransaction

@router.get("/", response_model=List[UserResponse])
async def list_users(
    role: Optional[UserRole] = None,
    include_inactive: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    stmt = select(User)
    if not include_inactive:
        stmt = stmt.where(User.is_active == True)
    if role:
        stmt = stmt.where(User.role == role)
    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()

@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi!")
    return user

@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_in: UserUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi!")

    update_data = user_in.model_dump(exclude_unset=True)

    # Telefon raqami o'zgartirilayotgan bo'lsa, takroriylikni tekshirish
    if "phone" in update_data and update_data["phone"] and update_data["phone"] != user.phone:
        existing_phone = await db.execute(
            select(User).where(User.phone == update_data["phone"], User.id != user_id)
        )
        if existing_phone.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Ushbu telefon raqamiga ega boshqa foydalanuvchi allaqachon mavjud!")

    for field, value in update_data.items():
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)
    return user

@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    permanent: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi!")

    if permanent:
        # Bog'langan yozuvlarni tozalash
        from sqlalchemy import delete
        from app.models.models import Attendance, HomeworkSubmission, Payment, StudentBilling, ExamResult, Certificate, SupportTicket
        await db.execute(delete(GroupStudent).where(GroupStudent.student_id == user_id))
        await db.execute(delete(ParentStudent).where((ParentStudent.student_id == user_id) | (ParentStudent.parent_id == user_id)))
        await db.execute(delete(CoinTransaction).where(CoinTransaction.student_id == user_id))
        await db.execute(delete(Attendance).where(Attendance.student_id == user_id))
        await db.execute(delete(HomeworkSubmission).where(HomeworkSubmission.student_id == user_id))
        await db.execute(delete(ExamResult).where(ExamResult.student_id == user_id))
        await db.execute(delete(Certificate).where(Certificate.student_id == user_id))
        await db.execute(delete(StudentBilling).where(StudentBilling.student_id == user_id))
        await db.execute(delete(Payment).where(Payment.student_id == user_id))
        await db.execute(delete(StudentFreeze).where(StudentFreeze.student_id == user_id))
        await db.execute(delete(SupportTicket).where(SupportTicket.user_id == user_id))
        await db.delete(user)
        await db.commit()
        logger.info(f"Foydalanuvchi bazadan to'liq o'chirildi: {user.login_id}")
        return {"message": f"Foydalanuvchi '{user.full_name}' tizimdan butunlay o'chirildi!"}
    else:
        user.is_active = False
        user.student_status = StudentStatusEnum.ARCHIVED
        await db.commit()
        logger.info(f"Foydalanuvchi deaktivlashtirildi: {user.login_id}")
        return {"message": f"Foydalanuvchi '{user.full_name}' muvaffaqiyatli o'chirildi (deaktivlashtirildi)!"}



# StudentFreeze endpoints (AUTH QOSHILDI)
@router.get("/freezes/", response_model=List[StudentFreezeResponse])
async def get_student_freezes(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    result = await db.execute(select(StudentFreeze))
    return result.scalars().all()

@router.post("/freezes/", response_model=StudentFreezeResponse)
async def create_student_freeze(
    freeze_in: StudentFreezeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    new_freeze = StudentFreeze(**freeze_in.model_dump())
    db.add(new_freeze)

    # O'quvchining asosiy holatini ham muzlatilgan (FROZEN) holatga sinxronlashtirish
    st_res = await db.execute(select(User).where(User.id == freeze_in.student_id))
    st = st_res.scalar_one_or_none()
    if st:
        st.student_status = StudentStatusEnum.FROZEN

    await db.commit()
    await db.refresh(new_freeze)
    return new_freeze

# GroupTransferLog endpoints (AUTH QOSHILDI)
@router.get("/transfers/", response_model=List[GroupTransferLogResponse])
async def get_group_transfers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    result = await db.execute(select(GroupTransferLog))
    return result.scalars().all()

@router.post("/transfers/", response_model=GroupTransferLogResponse)
async def create_group_transfer(
    transfer_in: GroupTransferLogCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    new_transfer = GroupTransferLog(**transfer_in.model_dump())
    db.add(new_transfer)
    await db.commit()
    await db.refresh(new_transfer)
    return new_transfer

# ParentStudent endpoints (AUTH QOSHILDI)
@router.get("/parent-student/", response_model=List[ParentStudentResponse])
async def get_parent_students(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    result = await db.execute(select(ParentStudent))
    return result.scalars().all()

@router.post("/parent-student/", response_model=ParentStudentResponse)
async def create_parent_student(
    ps_in: ParentStudentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    exist_res = await db.execute(
        select(ParentStudent).where(
            ParentStudent.parent_id == ps_in.parent_id,
            ParentStudent.student_id == ps_in.student_id
        )
    )
    existing = exist_res.scalar_one_or_none()
    if existing:
        existing.relationship_type = ps_in.relationship_type
        await db.commit()
        return existing

    new_ps = ParentStudent(**ps_in.model_dump())
    db.add(new_ps)
    await db.commit()
    return ps_in

# TelegramNotificationLog endpoints (AUTH QOSHILDI)
@router.get("/notifications/", response_model=List[TelegramNotificationLogResponse])
async def get_notifications(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    result = await db.execute(select(TelegramNotificationLog))
    return result.scalars().all()
