from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.models import Course, Room, User, CourseMaterial
from app.schemas.schemas import (
    CourseCreate, CourseUpdate, CourseResponse,
    RoomCreate, RoomUpdate, RoomResponse,
    CourseMaterialCreate, CourseMaterialResponse
)
from app.api.deps import get_current_admin, get_current_user

router = APIRouter()

# Rooms Endpoints
@router.post("/rooms", response_model=RoomResponse)
async def create_room(room_in: RoomCreate, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin)):
    room = Room(**room_in.model_dump())
    db.add(room)
    await db.commit()
    await db.refresh(room)
    return room

@router.get("/rooms", response_model=List[RoomResponse])
async def list_rooms(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(Room))
    return result.scalars().all()

@router.get("/rooms/{room_id}", response_model=RoomResponse)
async def get_room(room_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    res = await db.execute(select(Room).where(Room.id == room_id))
    room = res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Dars xonasi topilmadi!")
    return room

@router.put("/rooms/{room_id}", response_model=RoomResponse)
async def update_room(room_id: int, room_in: RoomUpdate, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin)):
    res = await db.execute(select(Room).where(Room.id == room_id))
    room = res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Dars xonasi topilmadi!")
    for field, value in room_in.model_dump(exclude_unset=True).items():
        setattr(room, field, value)
    await db.commit()
    await db.refresh(room)
    return room

@router.delete("/rooms/{room_id}")
async def delete_room(room_id: int, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin)):
    res = await db.execute(select(Room).where(Room.id == room_id))
    room = res.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Dars xonasi topilmadi!")
    await db.delete(room)
    await db.commit()
    return {"message": "Dars xonasi muvaffaqiyatli o'chirildi!"}

# Courses Endpoints
@router.post("/", response_model=CourseResponse)
async def create_course(course_in: CourseCreate, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin)):
    course = Course(**course_in.model_dump())
    db.add(course)
    await db.commit()
    await db.refresh(course)
    return course

@router.get("/", response_model=List[CourseResponse])
async def list_courses(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(Course))
    return result.scalars().all()

@router.get("/{course_id}", response_model=CourseResponse)
async def get_course(course_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    res = await db.execute(select(Course).where(Course.id == course_id))
    course = res.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Kurs topilmadi!")
    return course

@router.put("/{course_id}", response_model=CourseResponse)
async def update_course(course_id: int, course_in: CourseUpdate, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin)):
    res = await db.execute(select(Course).where(Course.id == course_id))
    course = res.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Kurs topilmadi!")
    for field, value in course_in.model_dump(exclude_unset=True).items():
        setattr(course, field, value)
    await db.commit()
    await db.refresh(course)
    return course

@router.delete("/{course_id}")
async def delete_course(course_id: int, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin)):
    res = await db.execute(select(Course).where(Course.id == course_id))
    course = res.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Kurs topilmadi!")
    # Soft delete
    course.is_active = False
    await db.commit()
    return {"message": "Kurs muvaffaqiyatli deaktivlashtirildi!"}

# Course Materials (AUTH QOSHILDI)
@router.get("/materials/", response_model=List[CourseMaterialResponse])
async def get_course_materials(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(CourseMaterial))
    return result.scalars().all()

@router.post("/materials/", response_model=CourseMaterialResponse)
async def create_course_material(material_in: CourseMaterialCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    new_material = CourseMaterial(**material_in.model_dump(), uploaded_by_id=current_user.id)
    db.add(new_material)
    await db.commit()
    await db.refresh(new_material)
    return new_material
