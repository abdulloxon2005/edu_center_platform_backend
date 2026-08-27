from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.models import RewardItem, RewardRedemption, CoinTransaction, User
from app.schemas.schemas import (
    RewardItemCreate, RewardItemResponse, RewardRedeemRequest,
    RewardRedemptionResponse, RedemptionStatusUpdate, CoinTransactionResponse
)
from app.api.deps import get_current_admin, get_current_student, get_current_user

router = APIRouter()

# Admin sovg'a item yaratadi
@router.post("/items", response_model=RewardItemResponse)
async def create_reward_item(
    item_in: RewardItemCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    item = RewardItem(**item_in.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item

@router.get("/items", response_model=List[RewardItemResponse])
async def list_reward_items(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    res = await db.execute(select(RewardItem).where(RewardItem.is_active == True))
    return res.scalars().all()

# Student coin evaziga sovg'a sotib oladi (Redeem)
@router.post("/redeem")
async def redeem_reward(
    redeem_in: RewardRedeemRequest,
    db: AsyncSession = Depends(get_db),
    student: User = Depends(get_current_student)
):
    # Item borligini tekshirish
    item_res = await db.execute(select(RewardItem).where(RewardItem.id == redeem_in.reward_item_id))
    item = item_res.scalar_one_or_none()
    if not item or not item.is_active:
        raise HTTPException(status_code=404, detail="Sovg'a topilmadi yoki faol emas!")

    if item.stock_quantity <= 0:
        raise HTTPException(status_code=400, detail="Kechirasiz, ushbu sovg'a omborda tugagan!")

    if student.coins_balance < item.coin_price:
        raise HTTPException(
            status_code=400,
            detail=f"Tangalaringiz yetarli emas! Sizda {student.coins_balance} coin bor, sovg'a narxi {item.coin_price} coin."
        )

    # Tangani kamaytirish va tranzaksiya yozish
    student.coins_balance -= item.coin_price
    item.stock_quantity -= 1

    redemption = RewardRedemption(
        student_id=student.id,
        reward_item_id=item.id,
        coins_spent=item.coin_price,
        status="PENDING"
    )
    db.add(redemption)

    coin_tx = CoinTransaction(
        student_id=student.id,
        amount=-item.coin_price,
        reason=f"Coin Shop: '{item.title}' sovg'asi sotib olindi"
    )
    db.add(coin_tx)

    await db.commit()
    return {"message": f"Tabriklaymiz! '{item.title}' sovg'asi uchun ariza qabul qilindi. Qolgan balansingiz: {student.coins_balance} coin."}

@router.get("/redemptions", response_model=List[RewardRedemptionResponse])
async def list_redemptions(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    res = await db.execute(select(RewardRedemption).order_by(RewardRedemption.created_at.desc()))
    return res.scalars().all()

@router.put("/redemptions/{redemption_id}/status")
async def update_redemption_status(
    redemption_id: int,
    status_in: RedemptionStatusUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    res = await db.execute(select(RewardRedemption).where(RewardRedemption.id == redemption_id))
    red = res.scalar_one_or_none()
    if not red:
        raise HTTPException(status_code=404, detail="Sovg'a arizasi topilmadi!")

    red.status = status_in.status
    await db.commit()
    return {"message": f"Sovg'a arizasi holati '{status_in.status}' ga o'zgartirildi!"}

@router.get("/student/transactions", response_model=List[CoinTransactionResponse])
async def get_student_coin_transactions(
    db: AsyncSession = Depends(get_db),
    student: User = Depends(get_current_student)
):
    res = await db.execute(
        select(CoinTransaction).where(CoinTransaction.student_id == student.id).order_by(CoinTransaction.created_at.desc())
    )
    return res.scalars().all()
