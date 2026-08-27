from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import get_password_hash, generate_secure_temp_password
from app.models.models import Lead, LeadStatus, User, UserRole
from app.schemas.schemas import LeadCreate, LeadStatusUpdate, LeadResponse
from app.api.deps import get_current_admin
from app.api.v1.users import generate_unique_login_id

router = APIRouter()

@router.post("/leads", response_model=LeadResponse)
async def create_lead(
    lead_in: LeadCreate,
    db: AsyncSession = Depends(get_db)
):
    lead = Lead(**lead_in.model_dump())
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    return lead

@router.get("/leads", response_model=List[LeadResponse])
async def list_leads(
    status: Optional[LeadStatus] = None,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    stmt = select(Lead)
    if status:
        stmt = stmt.where(Lead.status == status)
    result = await db.execute(stmt)
    return result.scalars().all()

@router.get("/leads/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    res = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = res.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead topilmadi!")
    return lead

@router.put("/leads/{lead_id}/status")
async def update_lead_status(
    lead_id: int,
    status_in: LeadStatusUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    res = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = res.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead topilmadi!")

    lead.status = status_in.status
    if status_in.notes:
        lead.notes = status_in.notes

    new_login_id = None
    temp_password = None
    if status_in.status == LeadStatus.ENROLLED:
        existing_user_res = await db.execute(select(User).where(User.phone == lead.phone))
        if not existing_user_res.scalar_one_or_none():
            new_login_id = await generate_unique_login_id(db)
            temp_password = generate_secure_temp_password()
            new_student = User(
                login_id=new_login_id,
                full_name=lead.full_name,
                phone=lead.phone,
                hashed_password=get_password_hash(temp_password),
                is_password_changed=False,
                role=UserRole.STUDENT,
                telegram_chat_id=lead.telegram_user_id
            )
            db.add(new_student)

    await db.commit()
    result = {"message": "Lead holati yangilandi!"}
    if new_login_id:
        result["message"] = f"Lead holati yangilandi va O'quvchi akkounti yaratildi!"
        result["new_login_id"] = new_login_id
        result["temp_password"] = temp_password
    return result

@router.delete("/leads/{lead_id}")
async def delete_lead(
    lead_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    res = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = res.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead topilmadi!")

    await db.delete(lead)
    await db.commit()
    return {"message": "Lead muvaffaqiyatli o'chirildi!"}
