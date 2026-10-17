import random
import logging
from io import BytesIO
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.security import get_password_hash
from app.models.models import (
    User, UserRole, StudentStatusEnum, StudentFreeze, GroupTransferLog,
    ParentStudent, TelegramNotificationLog, GroupStudent, CoinTransaction,
    Group, Course, Room, Payment, Attendance, AttendanceStatus, Lesson
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
    phone_val = user_in.phone.strip() if user_in.phone and user_in.phone.strip() else None
    if phone_val:
        stmt = select(User).where(User.phone == phone_val)
        result = await db.execute(stmt)
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Ushbu telefon raqamiga ega foydalanuvchi allaqachon mavjud!")

    login_id = user_in.login_id or await generate_unique_login_id(db)
    temp_password = user_in.password or "123456"

    father_phone_val = user_in.father_phone.strip() if user_in.father_phone and user_in.father_phone.strip() else None
    mother_phone_val = user_in.mother_phone.strip() if user_in.mother_phone and user_in.mother_phone.strip() else None
    parent_phone_val = user_in.parent_phone or father_phone_val or mother_phone_val

    db_user = User(
        login_id=login_id,
        full_name=user_in.full_name,
        phone=phone_val,
        father_phone=father_phone_val,
        mother_phone=mother_phone_val,
        parent_phone=parent_phone_val,
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

    # Parolni alohida ishlov berish
    new_password = update_data.pop("password", None)
    if new_password:
        user.hashed_password = get_password_hash(new_password)
        user.is_password_changed = False
        logger.info(f"Admin tomonidan foydalanuvchi paroli yangilandi: {user.login_id}")

    # Telefon raqami o'zgartirilayotgan bo'lsa, takroriylikni tekshirish
    if "phone" in update_data:
        phone_val = update_data["phone"].strip() if update_data["phone"] and isinstance(update_data["phone"], str) and update_data["phone"].strip() else None
        update_data["phone"] = phone_val
        if phone_val and phone_val != user.phone:
            existing_phone = await db.execute(
                select(User).where(User.phone == phone_val, User.id != user_id)
            )
            if existing_phone.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="Ushbu telefon raqamiga ega boshqa foydalanuvchi allaqachon mavjud!")

    if "father_phone" in update_data and isinstance(update_data["father_phone"], str):
        update_data["father_phone"] = update_data["father_phone"].strip() or None
    if "mother_phone" in update_data and isinstance(update_data["mother_phone"], str):
        update_data["mother_phone"] = update_data["mother_phone"].strip() or None

    for field, value in update_data.items():
        setattr(user, field, value)

    # parent_phone ni ham sinxronlashtirish
    if not user.parent_phone:
        user.parent_phone = user.father_phone or user.mother_phone

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


@router.get("/{user_id}/full-detail")
async def get_student_full_detail(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    user_res = await db.execute(select(User).where(User.id == user_id))
    user = user_res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi!")

    # 1. Enrolled groups
    gs_stmt = (
        select(GroupStudent, Group, Course, User.full_name.label("teacher_name"), Room.name.label("room_name"))
        .join(Group, GroupStudent.group_id == Group.id)
        .outerjoin(Course, Group.course_id == Course.id)
        .outerjoin(User, Group.teacher_id == User.id)
        .outerjoin(Room, Group.room_id == Room.id)
        .where(GroupStudent.student_id == user_id)
    )
    gs_res = await db.execute(gs_stmt)
    groups_data = []
    for gs, g, crs, t_name, r_name in gs_res.all():
        groups_data.append({
            "group_id": g.id,
            "group_name": g.name,
            "course_title": crs.title if crs else "Fan biriktirilmagan",
            "teacher_name": t_name or "O'qituvchi tayinlanmagan",
            "days_of_week": g.days_of_week,
            "start_time": g.start_time,
            "end_time": g.end_time,
            "room_name": r_name or "Xona belgilanmagan",
            "tariff_type": gs.discount_type or "STANDARD",
            "custom_price": gs.custom_price,
            "discount_note": gs.discount_note,
            "joined_at": gs.joined_at.strftime("%Y-%m-%d") if getattr(gs, 'joined_at', None) else None,
            "is_active": g.is_active
        })

    # 2. Payments
    pay_res = await db.execute(
        select(Payment).where(Payment.student_id == user_id).order_by(Payment.created_at.desc())
    )
    payments = pay_res.scalars().all()
    payments_data = [
        {
            "id": p.id,
            "amount": p.amount,
            "month_for": p.month_for,
            "payment_method": p.payment_method,
            "discount_amount": p.discount_amount,
            "note": p.note,
            "created_at": p.created_at.strftime("%Y-%m-%d %H:%M") if p.created_at else None
        }
        for p in payments
    ]

    # 3. Attendance records
    att_stmt = (
        select(Attendance, Lesson.lesson_date, Lesson.topic, Group.name.label("group_name"))
        .join(Lesson, Attendance.lesson_id == Lesson.id)
        .join(Group, Lesson.group_id == Group.id)
        .where(Attendance.student_id == user_id)
        .order_by(Lesson.lesson_date.desc())
    )
    att_res = await db.execute(att_stmt)
    att_rows = att_res.all()

    total_att = len(att_rows)
    present_cnt = sum(1 for a, _, _, _ in att_rows if a.status == AttendanceStatus.PRESENT)
    late_cnt = sum(1 for a, _, _, _ in att_rows if a.status == AttendanceStatus.LATE)
    absent_cnt = sum(1 for a, _, _, _ in att_rows if a.status == AttendanceStatus.ABSENT)
    excused_cnt = sum(1 for a, _, _, _ in att_rows if a.status == AttendanceStatus.EXCUSED)
    att_rate = round(((present_cnt + late_cnt * 0.75) / total_att) * 100) if total_att > 0 else 0

    recent_attendances = [
        {
            "id": a.id,
            "date": str(l_date),
            "topic": topic,
            "group_name": grp_name,
            "status": a.status.value if hasattr(a.status, "value") else str(a.status),
            "note": a.note
        }
        for a, l_date, topic, grp_name in att_rows[:15]
    ]

    return {
        "student": {
            "id": user.id,
            "full_name": user.full_name,
            "login_id": user.login_id,
            "phone": user.phone,
            "father_phone": user.father_phone,
            "mother_phone": user.mother_phone,
            "parent_phone": user.parent_phone,
            "role": user.role,
            "student_status": user.student_status,
            "is_active": user.is_active,
            "telegram_chat_id": user.telegram_chat_id,
            "created_at": user.created_at.strftime("%Y-%m-%d %H:%M") if user.created_at else None
        },
        "groups": groups_data,
        "payments": payments_data,
        "attendance_summary": {
            "total": total_att,
            "present": present_cnt,
            "late": late_cnt,
            "absent": absent_cnt,
            "excused": excused_cnt,
            "rate": att_rate
        },
        "recent_attendances": recent_attendances
    }


@router.get("/{user_id}/full-detail/pdf")
async def get_student_full_detail_pdf(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    detail = await get_student_full_detail(user_id=user_id, db=db, admin=admin)
    st = detail["student"]
    groups = detail["groups"]
    payments = detail["payments"]
    att = detail["attendance_summary"]

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # Header
    p.setFillColorRGB(0.12, 0.23, 0.54)
    p.setFont("Helvetica-Bold", 18)
    p.drawString(50, height - 50, "Ta'lim Plus O'quv Markazi")
    p.setFont("Helvetica", 11)
    p.setFillColorRGB(0.4, 0.45, 0.55)
    p.drawString(50, height - 68, "O'quvchi to'liq ma'lumotnomasi va portfoliyasi")

    p.setStrokeColorRGB(0.8, 0.85, 0.95)
    p.setLineWidth(1)
    p.line(50, height - 76, width - 50, height - 76)

    # Student Info Card
    y = height - 105
    p.setFont("Helvetica-Bold", 14)
    p.setFillColorRGB(0.06, 0.09, 0.16)
    p.drawString(50, y, f"{st['full_name']}")
    p.setFont("Helvetica", 11)
    p.drawString(width - 200, y, f"Login ID: #{st['login_id']}")

    y -= 22
    p.setFont("Helvetica", 10)
    p.setFillColorRGB(0.3, 0.35, 0.45)
    phone_info = st['phone'] or 'Mavjud emas'
    parent_info = st['parent_phone'] or st['father_phone'] or st['mother_phone'] or 'Mavjud emas'
    p.drawString(50, y, f"Telefon: {phone_info} | Ota-onasi: {parent_info}")
    p.drawString(width - 200, y, f"Holati: {st['student_status'] or 'ACTIVE'}")

    y -= 18
    p.drawString(50, y, f"Ro'yxatdan o'tgan sana: {st['created_at'] or '-'}")

    # Enrolled Groups Section
    y -= 30
    p.setFillColorRGB(0.15, 0.39, 0.92)
    p.setFont("Helvetica-Bold", 12)
    p.drawString(50, y, "A'ZO BO'LGAN GURUHLARI:")

    y -= 18
    p.setFont("Helvetica", 10)
    p.setFillColorRGB(0.1, 0.15, 0.25)
    if not groups:
        p.drawString(60, y, "Hozirda biriktirilgan guruhlar mavjud emas.")
        y -= 16
    else:
        for g in groups:
            p.setFont("Helvetica-Bold", 10)
            p.drawString(60, y, f"- {g['group_name']} ({g['course_title']})")
            p.setFont("Helvetica", 9)
            p.drawString(240, y, f"O'qituvchi: {g['teacher_name']} | Xona: {g['room_name']}")
            y -= 14
            p.drawString(70, y, f"Jadval: {g['days_of_week']} ({g['start_time']} - {g['end_time']}) | Kelgan: {g.get('joined_at') or '-'} | Tarif: {g['tariff_type']}")
            y -= 18

    # Attendance Summary Section
    y -= 15
    p.setFillColorRGB(0.15, 0.39, 0.92)
    p.setFont("Helvetica-Bold", 12)
    p.drawString(50, y, "DAVOMAT KO'RSATKICHLARI:")

    y -= 18
    p.setFont("Helvetica", 10)
    p.setFillColorRGB(0.1, 0.15, 0.25)
    p.drawString(60, y, f"Jami darslar: {att['total']} ta | Keldi: {att['present']} | Kech qoldi: {att['late']} | Kelmadi: {att['absent']} | Sababli: {att['excused']}")
    y -= 16
    p.setFont("Helvetica-Bold", 10)
    p.drawString(60, y, f"Davomat darajasi: {att['rate']}%")

    # Payment History Section
    y -= 30
    p.setFillColorRGB(0.15, 0.39, 0.92)
    p.setFont("Helvetica-Bold", 12)
    p.drawString(50, y, "TO'LOVLAR TARIXI (Oxirgilari):")

    y -= 18
    p.setFont("Helvetica", 10)
    p.setFillColorRGB(0.1, 0.15, 0.25)
    if not payments:
        p.drawString(60, y, "To'lovlar yozuvi mavjud emas.")
        y -= 16
    else:
        for p_item in payments[:8]:
            p.setFont("Helvetica-Bold", 9)
            amt_str = f"{p_item['amount']:,.0f}" if p_item['amount'] is not None else "0"
            p.drawString(60, y, f"#{p_item['id']} - {amt_str} UZS")
            p.setFont("Helvetica", 9)
            p.drawString(200, y, f"Oy: {p_item['month_for'] or '-'} | Usul: {p_item['payment_method']} | Sana: {p_item['created_at']}")
            y -= 15

    # Footer
    p.setStrokeColorRGB(0.8, 0.85, 0.95)
    p.setLineWidth(1)
    p.line(50, 60, width - 50, 60)

    p.setFont("Helvetica-Oblique", 9)
    p.setFillColorRGB(0.5, 0.55, 0.65)
    p.drawString(50, 45, "Ta'lim Plus Elektron Boshqaruv Tizimi tomonidan avtomatik shakllantirildi.")
    p.drawRightString(width - 50, 45, f"Chop etilgan sana: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}")

    p.showPage()
    p.save()
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=student_{user_id}.pdf"}
    )
