from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.core.database import get_db
from app.models.models import Certificate, User, UserRole, Course
from app.schemas.schemas import CertificateCreate, CertificateResponse
from app.api.v1.auth import get_current_user

router = APIRouter()

@router.get("/", response_model=List[CertificateResponse])
async def get_certificates(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Barcha berilgan sertifikatlar ro'yxati (Admin va O'qituvchilar uchun)"""
    stmt = (
        select(Certificate, User.full_name.label("student_name"), User.login_id.label("student_login_id"), Course.title.label("course_title"))
        .join(User, Certificate.student_id == User.id)
        .join(Course, Certificate.course_id == Course.id)
        .order_by(Certificate.issue_date.desc(), Certificate.id.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    output = []
    for cert, s_name, s_login_id, c_title in rows:
        output.append(CertificateResponse(
            id=cert.id,
            certificate_code=cert.certificate_code,
            student_id=cert.student_id,
            student_name=s_name,
            student_login_id=s_login_id,
            course_id=cert.course_id,
            course_title=c_title,
            qr_hash=cert.qr_hash,
            issue_date=cert.issue_date
        ))
    return output


@router.get("/my", response_model=List[CertificateResponse])
async def get_my_certificates(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """O'quvchining o'z sertifikatlari ro'yxati"""
    stmt = (
        select(Certificate, User.full_name.label("student_name"), User.login_id.label("student_login_id"), Course.title.label("course_title"))
        .join(User, Certificate.student_id == User.id)
        .join(Course, Certificate.course_id == Course.id)
        .where(Certificate.student_id == current_user.id)
        .order_by(Certificate.issue_date.desc(), Certificate.id.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    output = []
    for cert, s_name, s_login_id, c_title in rows:
        output.append(CertificateResponse(
            id=cert.id,
            certificate_code=cert.certificate_code,
            student_id=cert.student_id,
            student_name=s_name,
            student_login_id=s_login_id,
            course_id=cert.course_id,
            course_title=c_title,
            qr_hash=cert.qr_hash,
            issue_date=cert.issue_date
        ))
    return output


@router.get("/student/{student_id}", response_model=List[CertificateResponse])
async def get_student_certificates(
    student_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Muayyan o'quvchining sertifikatlari"""
    stmt = (
        select(Certificate, User.full_name.label("student_name"), User.login_id.label("student_login_id"), Course.title.label("course_title"))
        .join(User, Certificate.student_id == User.id)
        .join(Course, Certificate.course_id == Course.id)
        .where(Certificate.student_id == student_id)
        .order_by(Certificate.issue_date.desc(), Certificate.id.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    output = []
    for cert, s_name, s_login_id, c_title in rows:
        output.append(CertificateResponse(
            id=cert.id,
            certificate_code=cert.certificate_code,
            student_id=cert.student_id,
            student_name=s_name,
            student_login_id=s_login_id,
            course_id=cert.course_id,
            course_title=c_title,
            qr_hash=cert.qr_hash,
            issue_date=cert.issue_date
        ))
    return output


@router.post("/", response_model=CertificateResponse, status_code=status.HTTP_201_CREATED)
async def create_certificate(
    certificate_in: CertificateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Admin tomonidan qo'lda sertifikat yaratish"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Ruxsat berilmagan!")

    new_certificate = Certificate(**certificate_in.model_dump())
    db.add(new_certificate)
    await db.commit()
    await db.refresh(new_certificate)

    s_res = await db.execute(select(User).where(User.id == new_certificate.student_id))
    student = s_res.scalar_one_or_none()
    c_res = await db.execute(select(Course).where(Course.id == new_certificate.course_id))
    course = c_res.scalar_one_or_none()

    return CertificateResponse(
        id=new_certificate.id,
        certificate_code=new_certificate.certificate_code,
        student_id=new_certificate.student_id,
        student_name=student.full_name if student else None,
        student_login_id=student.login_id if student else None,
        course_id=new_certificate.course_id,
        course_title=course.title if course else None,
        qr_hash=new_certificate.qr_hash,
        issue_date=new_certificate.issue_date
    )


@router.get("/verify/{certificate_code}", response_model=CertificateResponse)
async def verify_certificate(
    certificate_code: str,
    db: AsyncSession = Depends(get_db)
):
    """Sertifikatni unikal kodi yoki QR-hash orqali tekshirish (Ommaviy/Public)"""
    stmt = (
        select(Certificate, User.full_name.label("student_name"), User.login_id.label("student_login_id"), Course.title.label("course_title"))
        .join(User, Certificate.student_id == User.id)
        .join(Course, Certificate.course_id == Course.id)
        .where((Certificate.certificate_code == certificate_code) | (Certificate.qr_hash == certificate_code))
    )
    result = await db.execute(stmt)
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Sertifikat topilmadi yoki haqiqiy emas!")

    cert, s_name, s_login_id, c_title = row
    return CertificateResponse(
        id=cert.id,
        certificate_code=cert.certificate_code,
        student_id=cert.student_id,
        student_name=s_name,
        student_login_id=s_login_id,
        course_id=cert.course_id,
        course_title=c_title,
        qr_hash=cert.qr_hash,
        issue_date=cert.issue_date
    )


@router.get("/{id}", response_model=CertificateResponse)
async def get_certificate(id: int, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Certificate, User.full_name.label("student_name"), User.login_id.label("student_login_id"), Course.title.label("course_title"))
        .join(User, Certificate.student_id == User.id)
        .join(Course, Certificate.course_id == Course.id)
        .where(Certificate.id == id)
    )
    result = await db.execute(stmt)
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Sertifikat topilmadi!")

    cert, s_name, s_login_id, c_title = row
    return CertificateResponse(
        id=cert.id,
        certificate_code=cert.certificate_code,
        student_id=cert.student_id,
        student_name=s_name,
        student_login_id=s_login_id,
        course_id=cert.course_id,
        course_title=c_title,
        qr_hash=cert.qr_hash,
        issue_date=cert.issue_date
    )

