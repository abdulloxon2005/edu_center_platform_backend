import os
import shutil
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.config import settings
from app.models.models import Homework, HomeworkSubmission, HomeworkStatus, User, CoinTransaction, Group, GroupStudent
from app.schemas.schemas import HomeworkCreate, HomeworkResponse, HomeworkSubmissionResponse, HomeworkGradeRequest
from app.api.deps import get_current_teacher, get_current_student, get_current_user

router = APIRouter()

os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

def save_secure_upload(file: UploadFile, prefix: str) -> str:
    """Fayl kengaytmasini, hajmini va nomini xavfsiz holga keltirish"""
    safe_basename = os.path.basename(file.filename)
    ext = os.path.splitext(safe_basename)[1].lower()

    if ext not in settings.ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Xavfsizlik cheklovi: '{ext}' kengaytmali fayllarni yuklash taqiqlangan! Ruxsat berilganlar: {', '.join(settings.ALLOWED_UPLOAD_EXTENSIONS)}"
        )

    # Fayl hajmini tekshirish
    file.file.seek(0, 2)  # Fayl oxiriga o'tish
    file_size = file.file.tell()
    file.file.seek(0)  # Boshiga qaytish
    max_size_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file_size > max_size_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"Fayl hajmi {settings.MAX_UPLOAD_SIZE_MB} MB dan oshmasligi kerak! Joriy hajm: {file_size / (1024*1024):.1f} MB"
        )

    # UUID bilan noyob nom yaratish
    unique_id = uuid.uuid4().hex[:8]
    file_filename = f"{prefix}_{unique_id}{ext}"
    file_path = os.path.join(settings.UPLOAD_DIR, file_filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return f"/uploads/{file_filename}"

@router.post("/")
async def create_homework(
    group_id: int = Form(...),
    title: str = Form(...),
    description: Optional[str] = Form(None),
    max_coins: int = Form(10),
    file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    teacher: User = Depends(get_current_teacher)
):
    pdf_url = None
    if file and file.filename:
        pdf_url = save_secure_upload(file, f"hw_{group_id}")

    hw = Homework(
        group_id=group_id,
        teacher_id=teacher.id,
        title=title,
        description=description,
        max_coins=max_coins,
        pdf_file_url=pdf_url
    )
    db.add(hw)
    await db.commit()
    await db.refresh(hw)
    return hw

@router.get("/group/{group_id}", response_model=List[HomeworkResponse])
async def list_group_homeworks(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stmt = select(Homework).where(Homework.group_id == group_id).order_by(Homework.created_at.desc())
    res = await db.execute(stmt)
    return res.scalars().all()

@router.post("/submit")
async def submit_homework(
    homework_id: int = Form(...),
    text_submission: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    student: User = Depends(get_current_student)
):
    file_url = None
    if file and file.filename:
        file_url = save_secure_upload(file, f"sub_{homework_id}_{student.id}")

    sub = HomeworkSubmission(
        homework_id=homework_id,
        student_id=student.id,
        text_submission=text_submission,
        file_url=file_url,
        status=HomeworkStatus.PENDING
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return {"message": "Uy vazifasi muvaffaqiyatli topshirildi!", "submission_id": sub.id}


@router.get("/{homework_id}/submissions", response_model=List[HomeworkSubmissionResponse])
async def list_homework_submissions(
    homework_id: int,
    db: AsyncSession = Depends(get_db),
    teacher: User = Depends(get_current_teacher)
):
    stmt = (
        select(HomeworkSubmission, User)
        .outerjoin(User, HomeworkSubmission.student_id == User.id)
        .where(HomeworkSubmission.homework_id == homework_id)
        .order_by(HomeworkSubmission.submitted_at.desc())
    )
    res = await db.execute(stmt)
    rows = res.all()
    out = []
    for sub, student in rows:
        out.append(HomeworkSubmissionResponse(
            id=sub.id,
            homework_id=sub.homework_id,
            student_id=sub.student_id,
            student_name=student.full_name if student else "O'quvchi",
            student_login_id=student.login_id if student else "",
            file_url=sub.file_url,
            text_submission=sub.text_submission,
            grade=sub.grade,
            coins_awarded=sub.coins_awarded,
            feedback=sub.feedback,
            status=sub.status,
            submitted_at=sub.submitted_at
        ))
    return out

@router.get("/student/assigned")
async def list_student_assigned_homeworks(
    db: AsyncSession = Depends(get_db),
    student: User = Depends(get_current_student)
):
    """O'quvchining guruhlari bo'yicha berilgan barcha uy vazifalari va uning topshirgan holati/balli/coinlari"""
    gs_stmt = select(GroupStudent.group_id).where(GroupStudent.student_id == student.id, GroupStudent.is_active == True)
    gs_res = await db.execute(gs_stmt)
    group_ids = [row[0] for row in gs_res.all()]
    if not group_ids:
        return []

    stmt = (
        select(Homework, Group.name.label("group_name"), User.full_name.label("teacher_name"))
        .join(Group, Homework.group_id == Group.id)
        .join(User, Homework.teacher_id == User.id)
        .where(Homework.group_id.in_(group_ids))
        .order_by(Homework.created_at.desc())
    )
    res = await db.execute(stmt)
    rows = res.all()

    out = []
    for hw, g_name, t_name in rows:
        sub_stmt = select(HomeworkSubmission).where(
            HomeworkSubmission.homework_id == hw.id,
            HomeworkSubmission.student_id == student.id
        ).order_by(HomeworkSubmission.submitted_at.desc())
        sub = (await db.execute(sub_stmt)).scalars().first()

        out.append({
            "id": hw.id,
            "group_id": hw.group_id,
            "group_name": g_name,
            "teacher_name": t_name,
            "title": hw.title,
            "description": hw.description,
            "pdf_file_url": hw.pdf_file_url,
            "max_coins": hw.max_coins,
            "created_at": hw.created_at,
            "submission": {
                "id": sub.id,
                "text_submission": sub.text_submission,
                "file_url": sub.file_url,
                "grade": sub.grade,
                "coins_awarded": sub.coins_awarded,
                "feedback": sub.feedback,
                "status": sub.status,
                "submitted_at": sub.submitted_at
            } if sub else None
        })

    return out

@router.get("/student/my", response_model=List[HomeworkSubmissionResponse])
async def my_homework_submissions(
    db: AsyncSession = Depends(get_db),
    student: User = Depends(get_current_student)
):
    stmt = select(HomeworkSubmission).where(HomeworkSubmission.student_id == student.id).order_by(HomeworkSubmission.submitted_at.desc())
    res = await db.execute(stmt)
    return res.scalars().all()

@router.post("/grade")
async def grade_homework(
    grade_in: HomeworkGradeRequest,
    db: AsyncSession = Depends(get_db),
    teacher: User = Depends(get_current_teacher)
):
    stmt = select(HomeworkSubmission).where(HomeworkSubmission.id == grade_in.submission_id)
    res = await db.execute(stmt)
    sub = res.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Bajarilgan vazifa topilmadi!")

    sub.grade = grade_in.grade
    sub.coins_awarded = grade_in.coins_awarded
    sub.feedback = grade_in.feedback
    sub.status = HomeworkStatus.GRADED

    student_res = await db.execute(select(User).where(User.id == sub.student_id))
    student = student_res.scalar_one_or_none()
    if student and grade_in.coins_awarded > 0:
        student.coins_balance += grade_in.coins_awarded
        coin_tx = CoinTransaction(
            student_id=student.id,
            amount=grade_in.coins_awarded,
            reason=f"Uy vazifasi uchun mukofot tangalari (HW #{sub.homework_id})"
        )
        db.add(coin_tx)

    await db.commit()
    return {"message": f"Vazifa baholandi ({grade_in.grade}). O'quvchiga {grade_in.coins_awarded} coin taqdim etildi!"}
