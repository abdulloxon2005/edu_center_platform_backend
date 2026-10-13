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
    lead_dict = lead_in.model_dump()
    if lead_dict.get("phone"):
        lead_dict["phone"] = lead_dict["phone"].strip() or None
    if lead_dict.get("father_phone"):
        lead_dict["father_phone"] = lead_dict["father_phone"].strip() or None
    if lead_dict.get("mother_phone"):
        lead_dict["mother_phone"] = lead_dict["mother_phone"].strip() or None

    lead = Lead(**lead_dict)
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

    target_student_id = None
    target_login_id = None
    temp_password = None

    if status_in.status == LeadStatus.ENROLLED:
        existing_user = None
        if lead.phone:
            existing_user_res = await db.execute(select(User).where(User.phone == lead.phone))
            existing_user = existing_user_res.scalar_one_or_none()

        if existing_user:
            if existing_user.role != UserRole.STUDENT:
                existing_user.role = UserRole.STUDENT
            existing_user.is_active = True
            if not existing_user.full_name and lead.full_name:
                existing_user.full_name = lead.full_name
            target_student_id = existing_user.id
            target_login_id = existing_user.login_id
        else:
            new_login_id = await generate_unique_login_id(db)
            temp_password = generate_secure_temp_password()
            parent_phone_val = lead.father_phone or lead.mother_phone
            new_student = User(
                login_id=new_login_id,
                full_name=lead.full_name,
                phone=lead.phone,
                father_phone=lead.father_phone,
                mother_phone=lead.mother_phone,
                parent_phone=parent_phone_val,
                hashed_password=get_password_hash(temp_password),
                is_password_changed=False,
                role=UserRole.STUDENT,
                telegram_chat_id=lead.telegram_user_id
            )
            db.add(new_student)
            await db.flush()
            target_student_id = new_student.id
            target_login_id = new_login_id

    await db.commit()
    result = {
        "message": "Lead holati yangilandi!",
        "lead_id": lead.id,
        "status": lead.status.value if hasattr(lead.status, "value") else str(lead.status)
    }
    if target_student_id:
        result["student_id"] = target_student_id
        result["new_login_id"] = target_login_id
        if temp_password:
            result["temp_password"] = temp_password
            result["message"] = f"Lead qabul qilindi va yangi O'quvchi akkounti yaratildi (ID: {target_login_id})!"
        else:
            result["message"] = f"Lead qabul qilindi va mavjud o'quvchi profili biriktirildi (ID: {target_login_id})!"
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
