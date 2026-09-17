from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import (
    verify_password, create_access_token, create_refresh_token,
    get_password_hash, validate_password_strength, verify_token
)
from app.models.models import User, UserRole
from app.schemas.schemas import Token, UserResponse, LoginRequest, ChangePasswordRequest, LinkTelegramChatRequest, TelegramLoginRequest
from app.api.deps import get_current_user

router = APIRouter()

@router.post("/login", response_model=Token)
async def login(login_data: LoginRequest, db: AsyncSession = Depends(get_db)):
    stmt = select(User).where(User.login_id == login_data.login_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not verify_password(login_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="6 talik ID raqami yoki parol noto'g'ri!"
        )
    
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Foydalanuvchi hisobi bloklangan!")

    access_token = create_access_token(subject=user.id)
    refresh_token = create_refresh_token(subject=user.id)
    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user_id=user.id,
        login_id=user.login_id,
        role=user.role,
        full_name=user.full_name,
        must_change_password=not user.is_password_changed
    )

@router.post("/refresh")
async def refresh_access_token(
    refresh_token: str,
    db: AsyncSession = Depends(get_db)
):
    """Refresh token orqali yangi access token olish"""
    payload = verify_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token yaroqsiz yoki muddati o'tgan!"
        )
    
    user_id = payload.get("sub")
    stmt = select(User).where(User.id == int(user_id))
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Foydalanuvchi topilmadi!")
    
    new_access_token = create_access_token(subject=user.id)
    return {"access_token": new_access_token, "token_type": "bearer"}

@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not verify_password(req.old_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Eski parol noto'g'ri!")
    
    password_error = validate_password_strength(req.new_password)
    if password_error:
        raise HTTPException(status_code=400, detail=password_error)

    current_user.hashed_password = get_password_hash(req.new_password)
    current_user.is_password_changed = True
    await db.commit()
    return {"message": "Parolingiz muvaffaqiyatli almashtirildi!"}

@router.post("/link-telegram")
async def link_telegram_chat(
    req: LinkTelegramChatRequest,
    db: AsyncSession = Depends(get_db)
):
    """Telegram Bot uchun: login_id orqali chat_id ni bazaga yozish (Bot chaqiradi, JWT talab qilinmaydi)"""
    # login_id formatini tekshirish (6 ta raqam)
    if not req.login_id or len(req.login_id) != 6 or not req.login_id.isdigit():
        raise HTTPException(status_code=400, detail="Login ID 6 talik raqam bo'lishi kerak!")

    stmt = select(User).where(User.login_id == req.login_id)
    res = await db.execute(stmt)
    student = res.scalar_one_or_none()

    if not student:
        raise HTTPException(status_code=404, detail="Ushbu ID raqamga ega o'quvchi topilmadi! Iltimos, ID ni tekshirib qayta kiriting.")

    student.telegram_chat_id = req.chat_id
    await db.commit()
    return {
        "message": f"O'quvchi '{student.full_name}' muvaffaqiyatli Telegram chat bilan bog'landi!",
        "student_name": student.full_name,
        "login_id": student.login_id
    }

@router.post("/telegram-login", response_model=Token)
async def telegram_login(req: TelegramLoginRequest, db: AsyncSession = Depends(get_db)):
    """Telegram Mini App orqali telegram_chat_id bo'yicha tezkor kirish"""
    if not req.telegram_id:
        raise HTTPException(status_code=400, detail="Telegram ID kiritilmadi!")

    stmt = select(User).where(User.telegram_chat_id == req.telegram_id, User.is_active == True)
    res = await db.execute(stmt)
    user = res.scalars().first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="Ushbu Telegram akkauntga biriktirilgan foydalanuvchi topilmadi. Iltimos, 6 talik ID orqali kiring."
        )

    access_token = create_access_token(subject=user.id)
    refresh_token = create_refresh_token(subject=user.id)
    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user_id=user.id,
        login_id=user.login_id,
        role=user.role,
        full_name=user.full_name,
        must_change_password=not user.is_password_changed
    )

@router.get("/me", response_model=UserResponse)
async def read_current_user(current_user: User = Depends(get_current_user)):
    return current_user
