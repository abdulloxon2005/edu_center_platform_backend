from datetime import datetime, date, time, timezone
import enum
from typing import Optional, List
from sqlalchemy import (
    String, Integer, Float, Boolean, DateTime, Date, Time, Text, Enum as SQLEnum,
    ForeignKey, Table, Column, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

def utcnow():
    return datetime.now(timezone.utc)

class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    TEACHER = "TEACHER"
    STUDENT = "STUDENT"
    PARENT = "PARENT"
    STAFF = "STAFF"

class StudentStatusEnum(str, enum.Enum):
    ACTIVE = "ACTIVE"
    TRIAL = "TRIAL"
    FROZEN = "FROZEN"
    TRANSFERRED = "TRANSFERRED"
    GRADUATED = "GRADUATED"
    DROPPED = "DROPPED"
    BLOCKED = "BLOCKED"
    ARCHIVED = "ARCHIVED"

class PaymentMethod(str, enum.Enum):
    CASH = "CASH"
    CARD = "CARD"
    CLICK = "CLICK"
    PAYME = "PAYME"
    UZUM = "UZUM"
    BANK_TRANSFER = "BANK_TRANSFER"

class AttendanceStatus(str, enum.Enum):
    PRESENT = "PRESENT"
    LATE = "LATE"
    ABSENT = "ABSENT"
    EXCUSED = "EXCUSED"

class HomeworkStatus(str, enum.Enum):
    PENDING = "PENDING"
    GRADED = "GRADED"

class LeadStatus(str, enum.Enum):
    NEW = "NEW"
    CONTACTED = "CONTACTED"
    TRIAL_SCHEDULED = "TRIAL_SCHEDULED"
    ENROLLED = "ENROLLED"
    REJECTED = "REJECTED"

class ExamTypeEnum(str, enum.Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"

class ExamStatusEnum(str, enum.Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"

# Branch Table
class Branch(Base):
    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    address: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    manager_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

# Parent and Student Association
class ParentStudent(Base):
    __tablename__ = "parent_students"
    parent_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    relationship_type: Mapped[Optional[str]] = mapped_column(String(50), default="Parent")

# Group and Student Association
class GroupStudent(Base):
    __tablename__ = "group_students"
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    custom_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    discount_type: Mapped[Optional[str]] = mapped_column(String(50), default="STANDARD")  # STANDARD, GRANT_100, DISCOUNT_50, CHILD_TARIFF, ADULT_TARIFF, PRORATED, CUSTOM
    discount_note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    login_id: Mapped[str] = mapped_column(String(6), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(20), unique=True, index=True, nullable=True)
    father_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    mother_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    parent_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_password_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    role: Mapped[UserRole] = mapped_column(SQLEnum(UserRole), default=UserRole.STUDENT, nullable=False)
    student_status: Mapped[StudentStatusEnum] = mapped_column(SQLEnum(StudentStatusEnum), default=StudentStatusEnum.ACTIVE)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    telegram_chat_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    coins_balance: Mapped[int] = mapped_column(Integer, default=0)
    branch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("branches.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # Relationships
    taught_groups: Mapped[List["Group"]] = relationship("Group", back_populates="teacher")
    payments: Mapped[List["Payment"]] = relationship("Payment", back_populates="student")
    submissions: Mapped[List["HomeworkSubmission"]] = relationship("HomeworkSubmission", back_populates="student")

class StudentFreeze(Base):
    __tablename__ = "student_freezes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class GroupTransferLog(Base):
    __tablename__ = "group_transfer_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    old_group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), nullable=False)
    new_group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class Waitlist(Base):
    __tablename__ = "waitlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, default=20)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    groups: Mapped[List["Group"]] = relationship("Group", back_populates="room")

class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price_monthly: Mapped[float] = mapped_column(Float, nullable=False)
    duration_months: Mapped[int] = mapped_column(Integer, default=3)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    groups: Mapped[List["Group"]] = relationship("Group", back_populates="course")
    materials: Mapped[List["CourseMaterial"]] = relationship("CourseMaterial", back_populates="course")

class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), nullable=False)
    
    days_of_week: Mapped[str] = mapped_column(String(50), nullable=False)
    start_time: Mapped[str] = mapped_column(String(10), nullable=False)
    end_time: Mapped[str] = mapped_column(String(10), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, default=16)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    course: Mapped["Course"] = relationship("Course", back_populates="groups")
    teacher: Mapped["User"] = relationship("User", back_populates="taught_groups")
    room: Mapped["Room"] = relationship("Room", back_populates="groups")
    lessons: Mapped[List["Lesson"]] = relationship("Lesson", back_populates="group")
    homeworks: Mapped[List["Homework"]] = relationship("Homework", back_populates="group")

class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), nullable=False)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), nullable=False)
    lesson_date: Mapped[date] = mapped_column(Date, nullable=False)
    topic: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    group: Mapped["Group"] = relationship("Group", back_populates="lessons")
    attendances: Mapped[List["Attendance"]] = relationship("Attendance", back_populates="lesson")

class Attendance(Base):
    __tablename__ = "attendances"
    __table_args__ = (
        UniqueConstraint('lesson_id', 'student_id', name='uq_lesson_student'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[AttendanceStatus] = mapped_column(SQLEnum(AttendanceStatus), default=AttendanceStatus.PRESENT)
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    lesson: Mapped["Lesson"] = relationship("Lesson", back_populates="attendances")

class Homework(Base):
    __tablename__ = "homeworks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), nullable=False)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pdf_file_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    max_coins: Mapped[int] = mapped_column(Integer, default=10)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    group: Mapped["Group"] = relationship("Group", back_populates="homeworks")
    submissions: Mapped[List["HomeworkSubmission"]] = relationship("HomeworkSubmission", back_populates="homework")

class HomeworkSubmission(Base):
    __tablename__ = "homework_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    homework_id: Mapped[int] = mapped_column(ForeignKey("homeworks.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    file_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    text_submission: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    grade: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    coins_awarded: Mapped[int] = mapped_column(Integer, default=0)
    feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[HomeworkStatus] = mapped_column(SQLEnum(HomeworkStatus), default=HomeworkStatus.PENDING)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    homework: Mapped["Homework"] = relationship("Homework", back_populates="submissions")
    student: Mapped["User"] = relationship("User", back_populates="submissions")

class CourseMaterial(Base):
    __tablename__ = "course_materials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    group_id: Mapped[Optional[int]] = mapped_column(ForeignKey("groups.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pdf_file_url: Mapped[str] = mapped_column(String(255), nullable=False)
    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    course: Mapped["Course"] = relationship("Course", back_populates="materials")

class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    payment_method: Mapped[PaymentMethod] = mapped_column(SQLEnum(PaymentMethod), default=PaymentMethod.CASH)
    transaction_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    month_for: Mapped[str] = mapped_column(String(20), nullable=False)
    discount_amount: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    student: Mapped["User"] = relationship("User", back_populates="payments")

class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    invoice_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    paid_amount: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="UNPAID")
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class RewardItem(Base):
    __tablename__ = "reward_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    coin_price: Mapped[int] = mapped_column(Integer, nullable=False)
    stock_quantity: Mapped[int] = mapped_column(Integer, default=10)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class RewardRedemption(Base):
    __tablename__ = "reward_redemptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    reward_item_id: Mapped[int] = mapped_column(ForeignKey("reward_items.id"), nullable=False)
    coins_spent: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class CoinTransaction(Base):
    __tablename__ = "coin_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    father_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    mother_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    course_id: Mapped[Optional[int]] = mapped_column(ForeignKey("courses.id"), nullable=True)
    status: Mapped[LeadStatus] = mapped_column(SQLEnum(LeadStatus), default=LeadStatus.NEW)
    telegram_user_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class TeacherPayroll(Base):
    __tablename__ = "teacher_payrolls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    month_for: Mapped[str] = mapped_column(String(20), nullable=False)
    percentage_rate: Mapped[float] = mapped_column(Float, default=40.0)
    calculated_salary: Mapped[float] = mapped_column(Float, nullable=False)
    paid_amount: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class StudentBilling(Base):
    __tablename__ = "student_billings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), nullable=False)
    month_for: Mapped[str] = mapped_column(String(20), nullable=False)
    amount_due: Mapped[float] = mapped_column(Float, nullable=False)
    amount_paid: Mapped[float] = mapped_column(Float, default=0.0)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    course_id: Mapped[Optional[int]] = mapped_column(ForeignKey("courses.id"), nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    correct_answer: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    course: Mapped[Optional["Course"]] = relationship("Course")
    created_by: Mapped["User"] = relationship("User")

class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), nullable=False)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    exam_type: Mapped[ExamTypeEnum] = mapped_column(SQLEnum(ExamTypeEnum), default=ExamTypeEnum.OFFLINE)
    status: Mapped[ExamStatusEnum] = mapped_column(SQLEnum(ExamStatusEnum), default=ExamStatusEnum.SCHEDULED)
    max_score: Mapped[float] = mapped_column(Float, default=100.0)
    pass_score: Mapped[float] = mapped_column(Float, default=70.0)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    questions_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    exam_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    results: Mapped[List["ExamResult"]] = relationship("ExamResult", back_populates="exam", cascade="all, delete-orphan")
    group: Mapped["Group"] = relationship("Group")
    teacher: Mapped["User"] = relationship("User")

class ExamResult(Base):
    __tablename__ = "exam_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    answers_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    exam: Mapped["Exam"] = relationship("Exam", back_populates="results")
    student: Mapped["User"] = relationship("User")

class Certificate(Base):
    __tablename__ = "certificates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    certificate_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    qr_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, default=date.today)

    student: Mapped["User"] = relationship("User")
    course: Mapped["Course"] = relationship("Course")

class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    user_name: Mapped[str] = mapped_column(String(150), nullable=False)
    user_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="NEW")
    admin_reply: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class TelegramNotificationLog(Base):
    __tablename__ = "telegram_notification_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    chat_id: Mapped[str] = mapped_column(String(50), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="SENT")
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_name: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
