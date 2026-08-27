from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.core.database import get_db
from app.models.models import Branch, User, UserRole
from app.schemas.schemas import BranchCreate, BranchResponse
from app.api.deps import get_current_user, get_current_admin

router = APIRouter()

@router.get("/", response_model=List[BranchResponse])
async def get_branches(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(Branch))
    return result.scalars().all()

@router.post("/", response_model=BranchResponse, status_code=status.HTTP_201_CREATED)
async def create_branch(branch_in: BranchCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_admin)):
    new_branch = Branch(**branch_in.model_dump())
    db.add(new_branch)
    await db.commit()
    await db.refresh(new_branch)
    return new_branch

@router.get("/{id}", response_model=BranchResponse)
async def get_branch(id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    branch = await db.get(Branch, id)
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    return branch
