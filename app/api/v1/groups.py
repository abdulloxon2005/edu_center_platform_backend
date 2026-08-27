from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.models import Group, GroupStudent, User, UserRole, Course, Room
from app.schemas.schemas import GroupCreate, GroupUpdate, GroupResponse, GroupDetailResponse, UserResponse
from app.api.deps import get_current_admin, get_current_user
from app.services.conflict_solver import validate_group_schedule

router = APIRouter()

async def resolve_or_create_room(db: AsyncSession, room_id: Optional[int], room_name: Optional[str]) -> int:
    if room_name and room_name.strip():
        name_clean = room_name.strip()
        res = await db.execute(select(Room).where(Room.name.ilike(name_clean)))
        room = res.scalar_one_or_none()
        if not room:
            room = Room(name=name_clean, capacity=20)
            db.add(room)
            await db.flush()
        return room.id
    if room_id:
        res = await db.execute(select(Room).where(Room.id == room_id))
        room = res.scalar_one_or_none()
        if room:
            return room.id
    # Default fallback
    res = await db.execute(select(Room))
    first_room = res.scalars().first()
    if first_room:
        return first_room.id
    new_room = Room(name="1-xona", capacity=20)
    db.add(new_room)
    await db.flush()
    return new_room.id

@router.post("/", response_model=GroupResponse)
async def create_group(
    group_in: GroupCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    resolved_room_id = await resolve_or_create_room(db, group_in.room_id, group_in.room_name)

    # 1. Dars jadvali va xona bandligida konflikt bor-yo'qligini tekshirish
    await validate_group_schedule(
        db=db,
        teacher_id=group_in.teacher_id,
        room_id=resolved_room_id,
        days_of_week=group_in.days_of_week,
        start_time=group_in.start_time,
        end_time=group_in.end_time
    )

    data = group_in.model_dump()
    data.pop("room_name", None)
    data["room_id"] = resolved_room_id
    group = Group(**data)
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return group

@router.get("/", response_model=List[GroupResponse])
async def list_groups(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stmt = select(Group)
    if current_user.role == UserRole.TEACHER:
        stmt = stmt.where(Group.teacher_id == current_user.id)
    result = await db.execute(stmt)
    return result.scalars().all()

@router.get("/{group_id}", response_model=GroupDetailResponse)
async def get_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    res = await db.execute(select(Group).where(Group.id == group_id))
    group = res.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Guruh topilmadi!")

    # Fetch Course, Teacher, Room, Students
    course_res = await db.execute(select(Course).where(Course.id == group.course_id))
    teacher_res = await db.execute(select(User).where(User.id == group.teacher_id))
    room_res = await db.execute(select(Room).where(Room.id == group.room_id))

    students_stmt = (
        select(User)
        .join(GroupStudent, GroupStudent.student_id == User.id)
        .where(GroupStudent.group_id == group_id, GroupStudent.is_active == True)
    )
    students_res = await db.execute(students_stmt)

    return GroupDetailResponse(
        id=group.id,
        name=group.name,
        course_id=group.course_id,
        teacher_id=group.teacher_id,
        room_id=group.room_id,
        days_of_week=group.days_of_week,
        start_time=group.start_time,
        end_time=group.end_time,
        is_active=group.is_active,
        created_at=group.created_at,
        course=course_res.scalar_one_or_none(),
        teacher=teacher_res.scalar_one_or_none(),
        room=room_res.scalar_one_or_none(),
        students=list(students_res.scalars().all())
    )

@router.put("/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: int,
    group_in: GroupUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    res = await db.execute(select(Group).where(Group.id == group_id))
    group = res.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Guruh topilmadi!")

    update_data = group_in.model_dump(exclude_unset=True)

    room_name = update_data.pop("room_name", None)
    room_id = update_data.get("room_id")
    if room_name or room_id is not None:
        resolved_room_id = await resolve_or_create_room(db, room_id, room_name)
        update_data["room_id"] = resolved_room_id

    # Schedule changes check
    teacher_id = update_data.get("teacher_id", group.teacher_id)
    target_room_id = update_data.get("room_id", group.room_id)
    days_of_week = update_data.get("days_of_week", group.days_of_week)
    start_time = update_data.get("start_time", group.start_time)
    end_time = update_data.get("end_time", group.end_time)

    await validate_group_schedule(
        db=db,
        teacher_id=teacher_id,
        room_id=target_room_id,
        days_of_week=days_of_week,
        start_time=start_time,
        end_time=end_time,
        exclude_group_id=group_id
    )

    for field, value in update_data.items():
        setattr(group, field, value)

    await db.commit()
    await db.refresh(group)
    return group

@router.delete("/{group_id}")
async def delete_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    res = await db.execute(select(Group).where(Group.id == group_id))
    group = res.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Guruh topilmadi!")

    group.is_active = False
    await db.commit()
    return {"message": f"Guruh '{group.name}' deaktivlashtirildi!"}

@router.post("/{group_id}/students/{student_id}")
async def assign_student_to_group(
    group_id: int,
    student_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    # Student borligini tekshirish
    student_res = await db.execute(select(User).where(User.id == student_id, User.role == UserRole.STUDENT))
    student = student_res.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="O'quvchi topilmadi!")

    # Guruh borligini tekshirish
    group_res = await db.execute(select(Group).where(Group.id == group_id))
    group = group_res.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Guruh topilmadi!")

    # Takroriy a'zolikni tekshirish
    exist_res = await db.execute(
        select(GroupStudent).where(GroupStudent.group_id == group_id, GroupStudent.student_id == student_id)
    )
    existing = exist_res.scalar_one_or_none()
    if existing:
        if not existing.is_active:
            existing.is_active = True
            await db.commit()
            return {"message": f"O'quvchi '{student.full_name}' guruhga qayta faollashtirildi!"}
        return {"message": f"O'quvchi '{student.full_name}' allaqachon ushbu guruhda mavjud!"}

    group_student = GroupStudent(group_id=group_id, student_id=student_id)
    db.add(group_student)
    await db.commit()
    return {"message": f"O'quvchi '{student.full_name}' muvaffaqiyatli '{group.name}' guruhiga qo'shildi!"}

@router.get("/{group_id}/students", response_model=List[UserResponse])
async def list_group_students(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stmt = (
        select(User)
        .join(GroupStudent, GroupStudent.student_id == User.id)
        .where(GroupStudent.group_id == group_id, GroupStudent.is_active == True)
    )
    res = await db.execute(stmt)
    return res.scalars().all()

@router.delete("/{group_id}/students/{student_id}")
async def remove_student_from_group(
    group_id: int,
    student_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    res = await db.execute(
        select(GroupStudent).where(GroupStudent.group_id == group_id, GroupStudent.student_id == student_id)
    )
    assoc = res.scalar_one_or_none()
    if not assoc:
        raise HTTPException(status_code=404, detail="O'quvchi ushbu guruhda topilmadi!")

    assoc.is_active = False
    await db.commit()
    return {"message": "O'quvchi guruhdan chiqarildi!"}


from app.models.models import Waitlist
from app.schemas.schemas import WaitlistCreate, WaitlistResponse

@router.get("/waitlist/", response_model=List[WaitlistResponse])
async def get_waitlists(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_admin)):
    result = await db.execute(select(Waitlist))
    return result.scalars().all()

@router.post("/waitlist/", response_model=WaitlistResponse)
async def create_waitlist(waitlist_in: WaitlistCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_admin)):
    new_waitlist = Waitlist(**waitlist_in.model_dump())
    db.add(new_waitlist)
    await db.commit()
    await db.refresh(new_waitlist)
    return new_waitlist
