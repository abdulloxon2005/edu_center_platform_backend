import json
import random
import re
from datetime import datetime, date
from io import BytesIO
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
import docx
import openpyxl

from app.core.database import get_db
from app.models.models import (
    Exam, ExamResult, User, UserRole, Group, Course, Attendance, HomeworkSubmission,
    Question, Certificate, GroupStudent
)
from app.schemas.schemas import (
    ExamCreate, ExamResponse, ExamSubmitRequest, ExamResultBulkCreate, ExamResultResponse,
    QuestionCreate, QuestionResponse, QuestionImportTextRequest,
    LeaderboardItem, StudentAnalyticsResponse
)
from app.api.deps import get_current_teacher, get_current_user, get_current_admin

router = APIRouter()

# ----------------------------------------------------
# HELPER FUNCTIONS: QUESTION PARSER & CERTIFICATE GENERATOR
# ----------------------------------------------------

def parse_questions_from_text(raw_text: str) -> List[dict]:
    """
    Format parser:
    ? Savol matni
    + To'g'ri javob
    - Noto'g'ri javob 1
    - Noto'g'ri javob 2
    - Noto'g'ri javob 3
    """
    lines = raw_text.splitlines()
    questions = []
    current_q = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Check for ? question indicator
        if stripped.startswith("?"):
            if current_q and len(current_q["options"]) >= 2:
                questions.append(current_q)
            q_text = stripped.lstrip("?").strip()
            # Remove optional leading numbering like 1. or 1)
            q_text = re.sub(r'^[0-9]+[\.\)]\s*', '', q_text)
            current_q = {
                "question_text": q_text,
                "options": [],
                "correct_answer": ""
            }
        elif stripped.startswith("+") and current_q:
            opt = stripped.lstrip("+").strip()
            opt = re.sub(r'^[A-Da-d][\.\)]\s*', '', opt)
            current_q["options"].append(opt)
            current_q["correct_answer"] = opt
        elif stripped.startswith("-") and current_q:
            opt = stripped.lstrip("-").strip()
            opt = re.sub(r'^[A-Da-d][\.\)]\s*', '', opt)
            current_q["options"].append(opt)
        # Fallback format: 1. Question / Q: Question / Savol: Question
        elif re.match(r'^(?:[0-9]+[\.\)]|Q:|Savol:)\s*', stripped, re.IGNORECASE):
            if current_q and len(current_q["options"]) >= 2:
                questions.append(current_q)
            q_text = re.sub(r'^(?:[0-9]+[\.\)]|Q:|Savol:)\s*', '', stripped, flags=re.IGNORECASE).strip()
            current_q = {
                "question_text": q_text,
                "options": [],
                "correct_answer": ""
            }
        # Fallback options: A) Option or * A) Option
        elif re.match(r'^\*?\s*[A-Da-d][\.\)]\s*', stripped) and current_q:
            is_correct = stripped.startswith("*")
            clean_opt = re.sub(r'^\*?\s*[A-Da-d][\.\)]\s*', '', stripped).strip()
            current_q["options"].append(clean_opt)
            if is_correct:
                current_q["correct_answer"] = clean_opt
        elif re.match(r'^(?:Javob|Answer):\s*', stripped, re.IGNORECASE) and current_q:
            ans = re.sub(r'^(?:Javob|Answer):\s*', '', stripped, flags=re.IGNORECASE).strip()
            current_q["correct_answer"] = ans

    if current_q and len(current_q["options"]) >= 2:
        questions.append(current_q)

    # Final validation & fallback for correct answers
    validated = []
    for q in questions:
        if q["question_text"] and len(q["options"]) >= 2:
            if not q["correct_answer"] or q["correct_answer"] not in q["options"]:
                q["correct_answer"] = q["options"][0]
            validated.append(q)

    return validated


async def generate_certificate_if_passed(
    db: AsyncSession,
    student_id: int,
    course_id: int
) -> Optional[Certificate]:
    """O'quvchi imtihondan o'tganda avtomatik unikal QR-kodli sertifikat yaratadi"""
    # Tekshirish: agar ushbu kurs uchun allaqachon sertifikat berilgan bo'lsa qaytarish
    cert_res = await db.execute(
        select(Certificate).where(
            Certificate.student_id == student_id,
            Certificate.course_id == course_id
        )
    )
    existing_cert = cert_res.scalar_one_or_none()
    if existing_cert:
        return existing_cert

    # Yangi unikal sertifikat kodi va QR hash yaratish
    year = datetime.now().year
    random_num = random.randint(10000, 99999)
    cert_code = f"CERT-{year}-{random_num}"
    qr_hash = f"TALIM_PLUS_{cert_code}_{student_id}_{course_id}"

    new_cert = Certificate(
        certificate_code=cert_code,
        student_id=student_id,
        course_id=course_id,
        qr_hash=qr_hash,
        issue_date=date.today()
    )
    db.add(new_cert)
    await db.flush()
    return new_cert


# ----------------------------------------------------
# 1. QUESTIONS BANK (SAVOLLAR BANKI & IMPORT)
# ----------------------------------------------------

@router.post("/questions", response_model=QuestionResponse)
async def create_question(
    q_in: QuestionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Qo'lda bitta savol qo'shish"""
    if current_user.role not in [UserRole.TEACHER, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Ruxsat berilmagan!")

    options_json = json.dumps(q_in.options, ensure_ascii=False)
    question = Question(
        course_id=q_in.course_id,
        created_by_id=current_user.id,
        question_text=q_in.question_text,
        correct_answer=q_in.correct_answer,
        options=options_json
    )
    db.add(question)
    await db.commit()
    await db.refresh(question)

    course_title = None
    if question.course_id:
        c_res = await db.execute(select(Course.title).where(Course.id == question.course_id))
        course_title = c_res.scalar_one_or_none()

    return QuestionResponse(
        id=question.id,
        course_id=question.course_id,
        course_title=course_title,
        created_by_id=question.created_by_id,
        question_text=question.question_text,
        correct_answer=question.correct_answer,
        options=json.loads(question.options),
        created_at=question.created_at
    )


@router.get("/questions", response_model=List[QuestionResponse])
async def list_questions(
    course_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Savollar bankidagi savollar ro'yxatini olish"""
    stmt = select(Question, Course.title.label("course_title")).outerjoin(Course, Question.course_id == Course.id)
    if course_id:
        stmt = stmt.where(Question.course_id == course_id)
    stmt = stmt.order_by(Question.created_at.desc())

    res = await db.execute(stmt)
    rows = res.all()

    results = []
    for q, c_title in rows:
        try:
            opts = json.loads(q.options) if isinstance(q.options, str) else q.options
        except Exception:
            opts = []
        results.append(QuestionResponse(
            id=q.id,
            course_id=q.course_id,
            course_title=c_title,
            created_by_id=q.created_by_id,
            question_text=q.question_text,
            correct_answer=q.correct_answer,
            options=opts,
            created_at=q.created_at
        ))
    return results


@router.delete("/questions/{question_id}")
async def delete_question(
    question_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Savolni savollar bankidan o'chirish"""
    if current_user.role not in [UserRole.TEACHER, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Ruxsat berilmagan!")

    q_res = await db.execute(select(Question).where(Question.id == question_id))
    q = q_res.scalar_one_or_none()
    if not q:
        raise HTTPException(status_code=404, detail="Savol topilmadi!")

    await db.delete(q)
    await db.commit()
    return {"message": "Savol muvaffaqiyatli o'chirildi!"}


@router.post("/questions/import-word")
async def import_questions_word(
    file: UploadFile = File(...),
    course_id: Optional[int] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Word (.docx) faylidan (?, +, -) formatidagi test savollarini avtomatik o'qib, Savollar Bankiga saqlash.
    """
    if current_user.role not in [UserRole.TEACHER, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Ruxsat berilmagan!")

    filename = file.filename.lower()
    if not filename.endswith(".docx"):
        raise HTTPException(status_code=400, detail="Faqat .docx (Word) fayllar qo'llab-quvvatlanadi!")

    content = await file.read()
    doc = docx.Document(BytesIO(content))
    raw_lines = [p.text for p in doc.paragraphs if p.text.strip()]
    raw_text = "\n".join(raw_lines)

    parsed_questions = parse_questions_from_text(raw_text)
    if not parsed_questions:
        raise HTTPException(status_code=400, detail="Fayldan savollar topilmadi! Iltimos, namunadagi (?, +, -) formatiga mosligini tekshiring.")

    saved_count = 0
    for q_data in parsed_questions:
        question = Question(
            course_id=course_id,
            created_by_id=current_user.id,
            question_text=q_data["question_text"],
            correct_answer=q_data["correct_answer"],
            options=json.dumps(q_data["options"], ensure_ascii=False)
        )
        db.add(question)
        saved_count += 1

    await db.commit()

    return {
        "message": f"{saved_count} ta test savoli Word fayldan muvaffaqiyatli yuklandi va Savollar Bankiga saqlandi!",
        "count": saved_count,
        "questions": parsed_questions
    }


@router.post("/questions/import-text")
async def import_questions_text(
    req: QuestionImportTextRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Matn shaklidagi (?, +, -) test savollarini parse qilib, Savollar Bankiga saqlash.
    """
    if current_user.role not in [UserRole.TEACHER, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Ruxsat berilmagan!")

    parsed_questions = parse_questions_from_text(req.raw_text)
    if not parsed_questions:
        raise HTTPException(status_code=400, detail="Matndan savollar topilmadi! Iltimos, (?, +, -) formatidan foydalaning.")

    saved_count = 0
    for q_data in parsed_questions:
        question = Question(
            course_id=req.course_id,
            created_by_id=current_user.id,
            question_text=q_data["question_text"],
            correct_answer=q_data["correct_answer"],
            options=json.dumps(q_data["options"], ensure_ascii=False)
        )
        db.add(question)
        saved_count += 1

    await db.commit()

    return {
        "message": f"{saved_count} ta test savoli muvaffaqiyatli saqlandi!",
        "count": saved_count,
        "questions": parsed_questions
    }


# ----------------------------------------------------
# 2. EXAMS MANAGEMENT (IMTIHONLAR YARATISH & BOSHQARISH)
# ----------------------------------------------------

@router.post("/exams", response_model=ExamResponse)
async def create_exam(
    exam_in: ExamCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Yangi Online yoki Offline imtihon yaratish"""
    if current_user.role not in [UserRole.TEACHER, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Ruxsat berilmagan!")

    group_res = await db.execute(select(Group).where(Group.id == exam_in.group_id))
    group = group_res.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Guruh topilmadi!")

    exam = Exam(
        group_id=exam_in.group_id,
        teacher_id=current_user.id,
        title=exam_in.title,
        exam_type=exam_in.exam_type.upper(),
        status="SCHEDULED",
        max_score=exam_in.max_score,
        pass_score=exam_in.pass_score,
        duration_minutes=exam_in.duration_minutes,
        questions_data=exam_in.questions_data,
        exam_date=exam_in.exam_date
    )
    db.add(exam)
    await db.commit()
    await db.refresh(exam)

    course_res = await db.execute(select(Course).where(Course.id == group.course_id))
    course = course_res.scalar_one_or_none()

    return ExamResponse(
        id=exam.id,
        group_id=exam.group_id,
        group_name=group.name,
        course_id=group.course_id,
        course_title=course.title if course else None,
        teacher_id=exam.teacher_id,
        teacher_name=current_user.full_name,
        title=exam.title,
        exam_type=exam.exam_type,
        status=exam.status,
        max_score=exam.max_score,
        pass_score=exam.pass_score,
        duration_minutes=exam.duration_minutes,
        questions_data=exam.questions_data,
        started_at=exam.started_at,
        exam_date=exam.exam_date,
        results_count=0,
        created_at=exam.created_at
    )


@router.get("/exams", response_model=List[ExamResponse])
async def list_all_exams(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Barcha imtihonlar ro'yxati (Admin va Teacher uchun)"""
    stmt = (
        select(Exam, Group.name.label("group_name"), Course.id.label("course_id"), Course.title.label("course_title"), User.full_name.label("teacher_name"))
        .join(Group, Exam.group_id == Group.id)
        .outerjoin(Course, Group.course_id == Course.id)
        .join(User, Exam.teacher_id == User.id)
        .order_by(Exam.exam_date.desc(), Exam.id.desc())
    )
    res = await db.execute(stmt)
    rows = res.all()

    exam_list = []
    for exam, g_name, c_id, c_title, t_name in rows:
        # Count results
        count_res = await db.execute(select(func.count(ExamResult.id)).where(ExamResult.exam_id == exam.id))
        r_count = count_res.scalar() or 0

        exam_list.append(ExamResponse(
            id=exam.id,
            group_id=exam.group_id,
            group_name=g_name,
            course_id=c_id,
            course_title=c_title,
            teacher_id=exam.teacher_id,
            teacher_name=t_name,
            title=exam.title,
            exam_type=exam.exam_type,
            status=exam.status,
            max_score=exam.max_score,
            pass_score=exam.pass_score,
            duration_minutes=exam.duration_minutes,
            questions_data=exam.questions_data,
            started_at=exam.started_at,
            exam_date=exam.exam_date,
            results_count=r_count,
            created_at=exam.created_at
        ))
    return exam_list


@router.get("/exams/group/{group_id}", response_model=List[ExamResponse])
async def list_group_exams(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Guruhga biriktirilgan imtihonlar"""
    stmt = (
        select(Exam, Group.name.label("group_name"), Course.id.label("course_id"), Course.title.label("course_title"), User.full_name.label("teacher_name"))
        .join(Group, Exam.group_id == Group.id)
        .outerjoin(Course, Group.course_id == Course.id)
        .join(User, Exam.teacher_id == User.id)
        .where(Exam.group_id == group_id)
        .order_by(Exam.exam_date.desc())
    )
    res = await db.execute(stmt)
    rows = res.all()

    exam_list = []
    for exam, g_name, c_id, c_title, t_name in rows:
        count_res = await db.execute(select(func.count(ExamResult.id)).where(ExamResult.exam_id == exam.id))
        r_count = count_res.scalar() or 0

        exam_list.append(ExamResponse(
            id=exam.id,
            group_id=exam.group_id,
            group_name=g_name,
            course_id=c_id,
            course_title=c_title,
            teacher_id=exam.teacher_id,
            teacher_name=t_name,
            title=exam.title,
            exam_type=exam.exam_type,
            status=exam.status,
            max_score=exam.max_score,
            pass_score=exam.pass_score,
            duration_minutes=exam.duration_minutes,
            questions_data=exam.questions_data,
            started_at=exam.started_at,
            exam_date=exam.exam_date,
            results_count=r_count,
            created_at=exam.created_at
        ))
    return exam_list


@router.get("/exams/student/my")
async def get_my_exams(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """O'quvchining o'z guruhlari bo'yicha barcha imtihonlari va natijalari"""
    if current_user.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Faqat o'quvchilar uchun!")

    # Student's enrolled groups
    g_res = await db.execute(
        select(GroupStudent.group_id).where(GroupStudent.student_id == current_user.id, GroupStudent.is_active == True)
    )
    group_ids = [row[0] for row in g_res.all()]
    if not group_ids:
        return []

    stmt = (
        select(Exam, Group.name.label("group_name"), Course.title.label("course_title"), Course.id.label("course_id"))
        .join(Group, Exam.group_id == Group.id)
        .outerjoin(Course, Group.course_id == Course.id)
        .where(Exam.group_id.in_(group_ids))
        .order_by(Exam.exam_date.desc(), Exam.id.desc())
    )
    res = await db.execute(stmt)
    exams = res.all()

    results = []
    for exam, g_name, c_title, c_id in exams:
        # Check student's submission
        res_stmt = select(ExamResult).where(ExamResult.exam_id == exam.id, ExamResult.student_id == current_user.id)
        my_result = (await db.execute(res_stmt)).scalar_one_or_none()

        # Check certificate
        cert_stmt = select(Certificate).where(Certificate.student_id == current_user.id, Certificate.course_id == c_id)
        my_cert = (await db.execute(cert_stmt)).scalar_one_or_none()

        # Sanitize questions_data for student if needed (or include if taking)
        q_data = None
        if exam.questions_data:
            try:
                q_parsed = json.loads(exam.questions_data)
                # Remove correct_answer when sending questions to student if active
                if exam.status == "ACTIVE":
                    q_data = [{ "question_text": q.get("question_text"), "options": q.get("options") } for q in q_parsed]
                else:
                    q_data = q_parsed
            except Exception:
                q_data = None

        results.append({
            "id": exam.id,
            "title": exam.title,
            "group_id": exam.group_id,
            "group_name": g_name,
            "course_id": c_id,
            "course_title": c_title,
            "exam_type": exam.exam_type,
            "status": exam.status,
            "max_score": exam.max_score,
            "pass_score": exam.pass_score,
            "duration_minutes": exam.duration_minutes,
            "started_at": exam.started_at,
            "exam_date": exam.exam_date,
            "has_submitted": my_result is not None,
            "my_score": my_result.score if my_result else None,
            "is_passed": (my_result.score >= exam.pass_score) if my_result else False,
            "certificate_code": my_cert.certificate_code if my_cert else None,
            "questions": q_data
        })

    return results


@router.post("/exams/{exam_id}/start", response_model=ExamResponse)
async def start_exam(
    exam_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Imtihonni boshlash (Status -> ACTIVE, started_at -> now)"""
    if current_user.role not in [UserRole.TEACHER, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Ruxsat berilmagan!")

    exam_res = await db.execute(select(Exam).where(Exam.id == exam_id))
    exam = exam_res.scalar_one_or_none()
    if not exam:
        raise HTTPException(status_code=404, detail="Imtihon topilmadi!")

    exam.status = "ACTIVE"
    exam.started_at = datetime.now()
    await db.commit()
    await db.refresh(exam)

    group_res = await db.execute(select(Group).where(Group.id == exam.group_id))
    group = group_res.scalar_one_or_none()

    return ExamResponse(
        id=exam.id,
        group_id=exam.group_id,
        group_name=group.name if group else "",
        teacher_id=exam.teacher_id,
        title=exam.title,
        exam_type=exam.exam_type,
        status=exam.status,
        max_score=exam.max_score,
        pass_score=exam.pass_score,
        duration_minutes=exam.duration_minutes,
        questions_data=exam.questions_data,
        started_at=exam.started_at,
        exam_date=exam.exam_date,
        created_at=exam.created_at
    )


@router.post("/exams/{exam_id}/finish", response_model=ExamResponse)
async def finish_exam(
    exam_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Imtihonni yakunlash (Status -> COMPLETED)"""
    if current_user.role not in [UserRole.TEACHER, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Ruxsat berilmagan!")

    exam_res = await db.execute(select(Exam).where(Exam.id == exam_id))
    exam = exam_res.scalar_one_or_none()
    if not exam:
        raise HTTPException(status_code=404, detail="Imtihon topilmadi!")

    exam.status = "COMPLETED"
    await db.commit()
    await db.refresh(exam)

    group_res = await db.execute(select(Group).where(Group.id == exam.group_id))
    group = group_res.scalar_one_or_none()

    return ExamResponse(
        id=exam.id,
        group_id=exam.group_id,
        group_name=group.name if group else "",
        teacher_id=exam.teacher_id,
        title=exam.title,
        exam_type=exam.exam_type,
        status=exam.status,
        max_score=exam.max_score,
        pass_score=exam.pass_score,
        duration_minutes=exam.duration_minutes,
        questions_data=exam.questions_data,
        started_at=exam.started_at,
        exam_date=exam.exam_date,
        created_at=exam.created_at
    )


@router.delete("/exams/{exam_id}")
async def delete_exam(
    exam_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Imtihonni va uning natijalarini o'chirish"""
    if current_user.role not in [UserRole.TEACHER, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Ruxsat berilmagan!")

    exam_res = await db.execute(select(Exam).where(Exam.id == exam_id))
    exam = exam_res.scalar_one_or_none()
    if not exam:
        raise HTTPException(status_code=404, detail="Imtihon topilmadi!")

    await db.delete(exam)
    await db.commit()
    return {"message": "Imtihon muvaffaqiyatli o'chirildi!"}


# ----------------------------------------------------
# 3. ONLINE & OFFLINE RESULTS & AUTOMATIC CERTIFICATES
# ----------------------------------------------------

@router.post("/exams/{exam_id}/submit")
async def submit_online_exam(
    exam_id: int,
    submission: ExamSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    O'quvchi tomonidan Online testni yechib topshirishi:
    Avtomatik tekshiradi, ball hisoblaydi, va agar ball >= pass_score bo'lsa avtomatik sertifikat yaratadi!
    """
    if current_user.role != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Faqat o'quvchilar test topshirishi mumkin!")

    exam_res = await db.execute(select(Exam).where(Exam.id == exam_id))
    exam = exam_res.scalar_one_or_none()
    if not exam:
        raise HTTPException(status_code=404, detail="Imtihon topilmadi!")

    # Parse questions from exam
    if not exam.questions_data:
        raise HTTPException(status_code=400, detail="Ushbu imtihon uchun test savollari biriktirilmagan!")

    questions = json.loads(exam.questions_data)
    total_q = len(questions)
    if total_q == 0:
        raise HTTPException(status_code=400, detail="Test savollari mavjud emas!")

    correct_count = 0
    student_answers = submission.answers

    for idx, q in enumerate(questions):
        idx_str = str(idx)
        selected_opt = student_answers.get(idx_str) or student_answers.get(idx)
        correct_opt = q.get("correct_answer")
        if selected_opt and str(selected_opt).strip().lower() == str(correct_opt).strip().lower():
            correct_count += 1

    # Score calculation
    percentage = round((correct_count / total_q) * 100, 1)
    calculated_score = round((correct_count / total_q) * exam.max_score, 1)
    is_passed = calculated_score >= exam.pass_score

    # Check if existing result
    res_stmt = select(ExamResult).where(ExamResult.exam_id == exam.id, ExamResult.student_id == current_user.id)
    result = (await db.execute(res_stmt)).scalar_one_or_none()

    if result:
        result.score = calculated_score
        result.answers_data = json.dumps(student_answers, ensure_ascii=False)
        result.feedback = f"{total_q} ta savoldan {correct_count} tasiga to'g'ri javob berildi ({percentage}%)"
    else:
        result = ExamResult(
            exam_id=exam.id,
            student_id=current_user.id,
            score=calculated_score,
            answers_data=json.dumps(student_answers, ensure_ascii=False),
            feedback=f"{total_q} ta savoldan {correct_count} tasiga to'g'ri javob berildi ({percentage}%)"
        )
        db.add(result)

    # Get course_id from group
    group_res = await db.execute(select(Group).where(Group.id == exam.group_id))
    group = group_res.scalar_one_or_none()

    cert_obj = None
    if is_passed and group:
        cert_obj = await generate_certificate_if_passed(db, current_user.id, group.course_id)

    await db.commit()

    return {
        "message": "Imtihon muvaffaqiyatli topshirildi!",
        "score": calculated_score,
        "max_score": exam.max_score,
        "percentage": percentage,
        "correct_answers": correct_count,
        "total_questions": total_q,
        "is_passed": is_passed,
        "certificate_awarded": is_passed and cert_obj is not None,
        "certificate_code": cert_obj.certificate_code if cert_obj else None
    }


@router.post("/exams/results")
async def record_exam_results(
    results_in: ExamResultBulkCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Offline yoki qo'lda o'tkazilgan imtihon natijalarini o'qituvchi/admin tomonidan kiritish:
    Har bir o'quvchining bali saqlanadi va agar ball >= pass_score bo'lsa avtomatik sertifikat beriladi!
    """
    if current_user.role not in [UserRole.TEACHER, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Ruxsat berilmagan!")

    exam_res = await db.execute(select(Exam).where(Exam.id == results_in.exam_id))
    exam = exam_res.scalar_one_or_none()
    if not exam:
        raise HTTPException(status_code=404, detail="Imtihon topilmadi!")

    group_res = await db.execute(select(Group).where(Group.id == exam.group_id))
    group = group_res.scalar_one_or_none()
    course_id = group.course_id if group else None

    saved_results_count = 0
    certificates_count = 0

    for item in results_in.results:
        # Check if result already exists for this student & exam
        res_stmt = select(ExamResult).where(
            ExamResult.exam_id == results_in.exam_id,
            ExamResult.student_id == item.student_id
        )
        existing = (await db.execute(res_stmt)).scalar_one_or_none()

        if existing:
            existing.score = item.score
            existing.feedback = item.feedback
        else:
            res = ExamResult(
                exam_id=results_in.exam_id,
                student_id=item.student_id,
                score=item.score,
                feedback=item.feedback
            )
            db.add(res)

        saved_results_count += 1

        # Check if student passed and generate certificate
        if course_id and item.score >= exam.pass_score:
            cert = await generate_certificate_if_passed(db, item.student_id, course_id)
            if cert:
                certificates_count += 1

    # Mark exam completed
    exam.status = "COMPLETED"
    await db.commit()

    return {
        "message": f"{saved_results_count} ta o'quvchi uchun imtihon natijalari saqlandi!",
        "results_count": saved_results_count,
        "certificates_awarded": certificates_count
    }


@router.get("/exams/{exam_id}/results", response_model=List[ExamResultResponse])
async def get_exam_results(
    exam_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Imtihon natijalarini to'liq ko'rish (Barcha o'quvchilar, ballar, sertifikatlar)"""
    exam_res = await db.execute(select(Exam).where(Exam.id == exam_id))
    exam = exam_res.scalar_one_or_none()
    if not exam:
        raise HTTPException(status_code=404, detail="Imtihon topilmadi!")

    group_res = await db.execute(select(Group).where(Group.id == exam.group_id))
    group = group_res.scalar_one_or_none()
    course_id = group.course_id if group else None

    stmt = (
        select(ExamResult, User.full_name, User.login_id)
        .join(User, ExamResult.student_id == User.id)
        .where(ExamResult.exam_id == exam_id)
        .order_by(ExamResult.score.desc())
    )
    res = await db.execute(stmt)
    rows = res.all()

    output = []
    for er, student_name, login_id in rows:
        percentage = round((er.score / exam.max_score) * 100, 1) if exam.max_score > 0 else 0.0
        is_passed = er.score >= exam.pass_score

        # Check certificate code
        cert_code = None
        if course_id:
            c_res = await db.execute(
                select(Certificate.certificate_code).where(
                    Certificate.student_id == er.student_id,
                    Certificate.course_id == course_id
                )
            )
            cert_code = c_res.scalar_one_or_none()

        output.append(ExamResultResponse(
            id=er.id,
            exam_id=er.exam_id,
            student_id=er.student_id,
            student_name=student_name,
            student_login_id=login_id,
            score=er.score,
            percentage=percentage,
            is_passed=is_passed,
            certificate_code=cert_code,
            feedback=er.feedback,
            answers_data=er.answers_data,
            created_at=er.created_at
        ))

    return output


# ----------------------------------------------------
# 4. LEADERBOARD & STUDENT ANALYTICS (REYTING VA ANALITIKA)
# ----------------------------------------------------

@router.get("/leaderboard", response_model=List[LeaderboardItem])
async def get_student_leaderboard(
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Eng ko'p tanga to'plagan eng kuchli Top N ta o'quvchi reytingi"""
    stmt = (
        select(User)
        .where(User.role == UserRole.STUDENT, User.is_active == True)
        .order_by(desc(User.coins_balance))
        .limit(limit)
    )
    res = await db.execute(stmt)
    top_students = res.scalars().all()

    leaderboard = []
    for index, st in enumerate(top_students, start=1):
        leaderboard.append(
            LeaderboardItem(
                rank=index,
                student_id=st.id,
                student_name=st.full_name,
                coins_balance=st.coins_balance
            )
        )
    return leaderboard


@router.get("/student/{student_id}", response_model=StudentAnalyticsResponse)
async def get_student_analytics(
    student_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """O'quvchining akademik ko'rsatkichlari: davomat %, vazifalar soni, tangalar va o'rtacha imtihon bali"""
    st_res = await db.execute(select(User).where(User.id == student_id, User.role == UserRole.STUDENT))
    student = st_res.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="O'quvchi topilmadi!")

    # Davomat statistikasi
    att_res = await db.execute(select(Attendance).where(Attendance.student_id == student_id))
    attendances = att_res.scalars().all()
    total_lessons = len(attendances)
    present_count = len([a for a in attendances if a.status in ["PRESENT", "LATE"]])
    attendance_rate = (present_count / total_lessons * 100.0) if total_lessons > 0 else 0.0

    # Uy vazifalari topshirig'i
    sub_res = await db.execute(select(func.count(HomeworkSubmission.id)).where(HomeworkSubmission.student_id == student_id))
    hw_count = sub_res.scalar() or 0

    # Imtihonlar o'rtacha bali
    exam_res = await db.execute(select(func.avg(ExamResult.score)).where(ExamResult.student_id == student_id))
    avg_score = exam_res.scalar() or 0.0

    return StudentAnalyticsResponse(
        student_id=student.id,
        full_name=student.full_name,
        total_lessons_attended=present_count,
        attendance_rate_percentage=round(attendance_rate, 1),
        homework_submissions_count=hw_count,
        coins_balance=student.coins_balance,
        average_exam_score=round(avg_score, 1)
    )


