import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete

from app.core.database import get_db
from app.models.models import Lesson, Attendance, AttendanceStatus, User, Group, Course, Room, GroupStudent, UserRole
from app.schemas.schemas import LessonCreate, LessonResponse, AttendanceBulkCreate, AttendanceResponse
from app.api.deps import get_current_user, get_current_admin
from app.services.notification import send_telegram_notification

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/lessons", response_model=LessonResponse)
async def create_lesson(
    lesson_in: LessonCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.ADMIN, UserRole.TEACHER]:
        raise HTTPException(status_code=403, detail="Dars yaratish uchun ruxsat yo'q!")

    group_res = await db.execute(select(Group).where(Group.id == lesson_in.group_id))
    group = group_res.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Guruh topilmadi!")

    room_id = lesson_in.room_id or group.room_id

    # Guruh va sana bo'yicha dars mavjudligini tekshiramiz
    existing_res = await db.execute(
        select(Lesson).where(
            Lesson.group_id == lesson_in.group_id,
            Lesson.lesson_date == lesson_in.lesson_date
        )
    )
    existing_lesson = existing_res.scalar_one_or_none()
    if existing_lesson:
        if lesson_in.topic:
            existing_lesson.topic = lesson_in.topic
        await db.commit()
        await db.refresh(existing_lesson)
        return existing_lesson

    lesson = Lesson(
        group_id=lesson_in.group_id,
        teacher_id=group.teacher_id if current_user.role == UserRole.ADMIN else current_user.id,
        room_id=room_id,
        lesson_date=lesson_in.lesson_date,
        topic=lesson_in.topic
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)
    return lesson

@router.get("/lessons", response_model=List[LessonResponse])
async def list_lessons(
    group_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stmt = select(Lesson)
    if group_id:
        stmt = stmt.where(Lesson.group_id == group_id)
    stmt = stmt.order_by(Lesson.lesson_date.desc())
    result = await db.execute(stmt)
    return result.scalars().all()

@router.delete("/lessons/{lesson_id}")
async def delete_lesson(
    lesson_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.ADMIN, UserRole.TEACHER]:
        raise HTTPException(status_code=403, detail="Darsni o'chirish uchun ruxsat yo'q!")

    lesson_res = await db.execute(select(Lesson).where(Lesson.id == lesson_id))
    lesson = lesson_res.scalar_one_or_none()
    if not lesson:
        raise HTTPException(status_code=404, detail="Dars mashg'uloti topilmadi!")

    # Darsga tegishli davomat yozuvlarini o'chirish
    await db.execute(delete(Attendance).where(Attendance.lesson_id == lesson_id))
    await db.delete(lesson)
    await db.commit()
    return {"message": "Dars sanasi muvaffaqiyatli o'chirildi!"}

@router.post("/mark")
async def mark_attendance(
    attendance_in: AttendanceBulkCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.ADMIN, UserRole.TEACHER]:
        raise HTTPException(status_code=403, detail="Davomat qilish uchun ruxsat yo'q!")

    lesson_res = await db.execute(select(Lesson).where(Lesson.id == attendance_in.lesson_id))
    lesson = lesson_res.scalar_one_or_none()
    if not lesson:
        raise HTTPException(status_code=404, detail="Dars mashg'uloti topilmadi!")

    created_records = []
    updated_records = []
    for item in attendance_in.attendances:
        existing = await db.execute(
            select(Attendance).where(
                Attendance.lesson_id == attendance_in.lesson_id,
                Attendance.student_id == item.student_id
            )
        )
        att = existing.scalar_one_or_none()
        if att:
            att.status = item.status
            if item.note is not None:
                att.note = item.note
            updated_records.append(att)
        else:
            att = Attendance(
                lesson_id=attendance_in.lesson_id,
                student_id=item.student_id,
                status=item.status,
                note=item.note
            )
            db.add(att)
            created_records.append(att)

        # Telegram bildirishnoma
        student_res = await db.execute(select(User).where(User.id == item.student_id))
        student = student_res.scalar_one_or_none()

        if student and student.telegram_chat_id:
            if item.status == AttendanceStatus.PRESENT:
                status_text = "Farzandingiz darsga KELDI ✅"
            elif item.status == AttendanceStatus.LATE:
                status_text = "Farzandingiz darsga KECHIKIB KELDI ⚠️"
            elif item.status == AttendanceStatus.ABSENT:
                status_text = "Farzandingiz darsga KELMADI ❌"
            else:
                status_text = "Farzandingiz darsda (Sababli 📋)"

            note_line = f"\n💬 Izoh: {item.note}" if item.note else ""
            msg = (
                f"🔔 <b>O'QUV MARKAZI DAVOMAT XABARI</b>\n\n"
                f"👤 Farzandingiz: <b>{student.full_name}</b> (ID: {student.login_id})\n"
                f"📅 Sana: {lesson.lesson_date}\n"
                f"📌 Holati: <b>{status_text}</b>"
                f"{note_line}"
            )
            await send_telegram_notification(student.telegram_chat_id, msg)

    await db.commit()
    msg = f"{len(created_records) + len(updated_records)} ta o'quvchi davomati saqlandi!"
    return {"message": msg, "created": len(created_records), "updated": len(updated_records)}

@router.get("/groups-summary")
async def get_groups_attendance_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Barcha faol guruhlar ro'yxati va har bir guruh bo'yicha so'nggi darsdagi davomat statistikasi (nechtadan nechta kelgani)"""
    groups_res = await db.execute(
        select(Group, Course, User, Room)
        .outerjoin(Course, Group.course_id == Course.id)
        .outerjoin(User, Group.teacher_id == User.id)
        .outerjoin(Room, Group.room_id == Room.id)
        .where(Group.is_active == True)
        .order_by(Group.name.asc())
    )
    group_rows = groups_res.all()

    summary_list = []
    for grp, crs, teacher, room in group_rows:
        # Guruhdagi faol talabalar soni
        st_stmt = select(func.count(GroupStudent.student_id)).where(
            GroupStudent.group_id == grp.id,
            GroupStudent.is_active == True
        )
        st_count_res = await db.execute(st_stmt)
        total_students = st_count_res.scalar() or 0

        # Guruhning so'nggi darsi
        lesson_stmt = select(Lesson).where(Lesson.group_id == grp.id).order_by(Lesson.lesson_date.desc(), Lesson.id.desc())
        lesson_res = await db.execute(lesson_stmt)
        latest_lesson = lesson_res.scalars().first()

        present_count = 0
        absent_count = 0
        late_count = 0
        excused_count = 0
        latest_date = None
        latest_topic = None

        if latest_lesson:
            latest_date = str(latest_lesson.lesson_date)
            latest_topic = latest_lesson.topic
            # Ushbu dars bo'yicha davomatlar
            att_stmt = select(Attendance).where(Attendance.lesson_id == latest_lesson.id)
            att_res = await db.execute(att_stmt)
            atts = att_res.scalars().all()
            for a in atts:
                if a.status == AttendanceStatus.PRESENT:
                    present_count += 1
                elif a.status == AttendanceStatus.LATE:
                    late_count += 1
                elif a.status == AttendanceStatus.ABSENT:
                    absent_count += 1
                elif a.status == AttendanceStatus.EXCUSED:
                    excused_count += 1

        summary_list.append({
            "group_id": grp.id,
            "group_name": grp.name,
            "course_id": crs.id if crs else grp.course_id,
            "course_title": crs.title if crs else "Kurs",
            "teacher_id": teacher.id if teacher else grp.teacher_id,
            "teacher_name": teacher.full_name if teacher else "O'qituvchi",
            "room_name": room.name if room else f"{grp.room_id}-xona",
            "days_of_week": grp.days_of_week,
            "start_time": grp.start_time,
            "end_time": grp.end_time,
            "total_students": total_students,
            "latest_lesson_id": latest_lesson.id if latest_lesson else None,
            "latest_lesson_date": latest_date,
            "latest_lesson_topic": latest_topic,
            "present_count": present_count,
            "late_count": late_count,
            "attended_count": present_count + late_count,
            "absent_count": absent_count,
            "excused_count": excused_count
        })

    return summary_list

@router.get("/group/{group_id}/journal")
async def get_group_attendance_journal(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Guruhdagi barcha o'quvchilar va dars sanalari bo'yicha to'liq davomat jurnali (matrix)"""
    group_res = await db.execute(
        select(Group, Course, User, Room)
        .outerjoin(Course, Group.course_id == Course.id)
        .outerjoin(User, Group.teacher_id == User.id)
        .outerjoin(Room, Group.room_id == Room.id)
        .where(Group.id == group_id)
    )
    group_row = group_res.first()
    if not group_row:
        raise HTTPException(status_code=404, detail="Guruh topilmadi!")
    grp, crs, teacher, room = group_row

    # 1. Guruhdagi faol o'quvchilar
    st_stmt = (
        select(User)
        .join(GroupStudent, GroupStudent.student_id == User.id)
        .where(
            GroupStudent.group_id == group_id,
            GroupStudent.is_active == True,
            User.is_active == True
        )
        .order_by(User.full_name.asc())
    )
    st_res = await db.execute(st_stmt)
    students = st_res.scalars().all()
    students_data = [
        {
            "id": s.id,
            "full_name": s.full_name,
            "login_id": s.login_id,
            "phone": s.phone,
            "student_status": s.student_status
        }
        for s in students
    ]

    # 2. Guruh darslari (sanalar tartibida: eng yangisi o'ngda yoki tartibli)
    lessons_stmt = select(Lesson).where(Lesson.group_id == group_id).order_by(Lesson.lesson_date.asc(), Lesson.id.asc())
    lessons_res = await db.execute(lessons_stmt)
    raw_lessons = lessons_res.scalars().all()

    # Bazadagi mavjud takroriy dars sanalarini bitta qilib birlashtirish (deduplicate & merge attendances)
    seen_dates = {}
    deduped_lessons = []
    lessons_to_delete = []

    for l in raw_lessons:
        d_str = str(l.lesson_date)
        if d_str not in seen_dates:
            seen_dates[d_str] = l
            deduped_lessons.append(l)
        else:
            primary_lesson = seen_dates[d_str]
            if not primary_lesson.topic and l.topic:
                primary_lesson.topic = l.topic

            # Takroriy darsdagi davomatlarni asosiy darsga ko'chirish
            dup_att_res = await db.execute(select(Attendance).where(Attendance.lesson_id == l.id))
            dup_atts = dup_att_res.scalars().all()
            for datt in dup_atts:
                existing_att_res = await db.execute(
                    select(Attendance).where(
                        Attendance.lesson_id == primary_lesson.id,
                        Attendance.student_id == datt.student_id
                    )
                )
                existing_att = existing_att_res.scalar_one_or_none()
                if not existing_att:
                    datt.lesson_id = primary_lesson.id
                else:
                    existing_att.status = datt.status
                    if datt.note:
                        existing_att.note = datt.note
                    await db.delete(datt)
            lessons_to_delete.append(l)

    if lessons_to_delete:
        for dl in lessons_to_delete:
            await db.delete(dl)
        await db.commit()

    lessons = deduped_lessons
    lessons_data = [
        {
            "id": l.id,
            "lesson_date": str(l.lesson_date),
            "topic": l.topic
        }
        for l in lessons
    ]

    # 3. Barcha davomat yozuvlari
    matrix = {}
    for s in students:
        matrix[str(s.id)] = {}

    lesson_ids = [l.id for l in lessons]
    if lesson_ids:
        att_stmt = select(Attendance).where(Attendance.lesson_id.in_(lesson_ids))
        att_res = await db.execute(att_stmt)
        attendances = att_res.scalars().all()
        for a in attendances:
            s_id_str = str(a.student_id)
            if s_id_str not in matrix:
                matrix[s_id_str] = {}
            matrix[s_id_str][str(a.lesson_id)] = {
                "id": a.id,
                "status": a.status,
                "note": a.note
            }

    return {
        "group": {
            "id": grp.id,
            "name": grp.name,
            "course_title": crs.title if crs else "Kurs",
            "teacher_name": teacher.full_name if teacher else "O'qituvchi",
            "room_name": room.name if room else f"{grp.room_id}-xona",
            "days_of_week": grp.days_of_week,
            "start_time": grp.start_time,
            "end_time": grp.end_time
        },
        "students": students_data,
        "lessons": lessons_data,
        "matrix": matrix
    }

@router.get("/student/{student_id}", response_model=List[AttendanceResponse])
async def get_student_attendance(
    student_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stmt = select(Attendance).where(Attendance.student_id == student_id).order_by(Attendance.created_at.desc())
    res = await db.execute(stmt)
    return res.scalars().all()

@router.get("/student/{student_id}/detailed")
async def get_student_attendance_detailed(
    student_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """O'quvchining davomat statistikasi: umumiy foiz, kelgan/kelmagan/kechikkan darslar va to'liq jurnali"""
    if current_user.role == UserRole.STUDENT and current_user.id != student_id:
        raise HTTPException(status_code=403, detail="Ruxsat berilmagan!")

    stmt = (
        select(Attendance, Lesson.lesson_date, Lesson.topic, Group.name.label("group_name"))
        .join(Lesson, Attendance.lesson_id == Lesson.id)
        .join(Group, Lesson.group_id == Group.id)
        .where(Attendance.student_id == student_id)
        .order_by(Lesson.lesson_date.desc(), Attendance.id.desc())
    )
    res = await db.execute(stmt)
    rows = res.all()

    records = []
    present_cnt = 0
    late_cnt = 0
    absent_cnt = 0
    excused_cnt = 0

    for att, l_date, topic, g_name in rows:
        if att.status == AttendanceStatus.PRESENT:
            present_cnt += 1
        elif att.status == AttendanceStatus.LATE:
            late_cnt += 1
        elif att.status == AttendanceStatus.ABSENT:
            absent_cnt += 1
        elif att.status == AttendanceStatus.EXCUSED:
            excused_cnt += 1

        records.append({
            "id": att.id,
            "lesson_id": att.lesson_id,
            "lesson_date": str(l_date),
            "topic": topic or "Dars mashg'uloti",
            "group_name": g_name,
            "status": att.status,
            "note": att.note,
            "created_at": att.created_at
        })

    total_lessons = len(records)
    attended = present_cnt + late_cnt
    rate = round((attended / total_lessons) * 100) if total_lessons > 0 else 100

    return {
        "total_lessons": total_lessons,
        "present_count": present_cnt,
        "late_count": late_cnt,
        "absent_count": absent_cnt,
        "excused_count": excused_cnt,
        "attendance_rate": rate,
        "records": records
    }

@router.get("/all")
async def list_all_attendances(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    stmt = (
        select(Attendance, User.full_name, User.login_id, Group.name.label("group_name"), Lesson.lesson_date)
        .join(User, Attendance.student_id == User.id)
        .join(Lesson, Attendance.lesson_id == Lesson.id)
        .join(Group, Lesson.group_id == Group.id)
        .order_by(Attendance.created_at.desc())
        .limit(100)
    )
    result = await db.execute(stmt)
    rows = result.all()
    return [
        {
            "id": att.id,
            "date": str(lesson_date),
            "student_name": f"{full_name} ({login_id})",
            "group_name": group_name,
            "status": "Present" if att.status == AttendanceStatus.PRESENT else ("Late" if att.status == AttendanceStatus.LATE else ("Absent" if att.status == AttendanceStatus.ABSENT else "Excused")),
            "note": att.note
        }
        for att, full_name, login_id, group_name, lesson_date in rows
    ]

