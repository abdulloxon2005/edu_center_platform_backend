from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.core.database import get_db
from app.models.models import SupportTicket, User, UserRole
from app.schemas.schemas import SupportTicketCreate, SupportTicketResponse, SupportTicketStatusUpdate
from app.api.deps import get_current_user, get_current_admin

router = APIRouter()

@router.get("/tickets/", response_model=List[SupportTicketResponse])
async def get_support_tickets(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.ADMIN:
        result = await db.execute(select(SupportTicket).where(SupportTicket.user_id == current_user.id))
    else:
        result = await db.execute(select(SupportTicket))
    return result.scalars().all()

@router.post("/tickets/", response_model=SupportTicketResponse, status_code=status.HTTP_201_CREATED)
async def create_support_ticket(ticket_in: SupportTicketCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    new_ticket = SupportTicket(**ticket_in.model_dump(), user_id=current_user.id)
    db.add(new_ticket)
    await db.commit()
    await db.refresh(new_ticket)
    return new_ticket

@router.put("/tickets/{id}/status", response_model=SupportTicketResponse)
async def update_support_ticket_status(id: int, status_update: SupportTicketStatusUpdate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_admin)):
    ticket = await db.get(SupportTicket, id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Support ticket not found")
    ticket.status = status_update.status
    if status_update.admin_reply is not None:
        ticket.admin_reply = status_update.admin_reply
    await db.commit()
    await db.refresh(ticket)
    return ticket
