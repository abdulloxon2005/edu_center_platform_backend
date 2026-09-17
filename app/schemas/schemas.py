from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime, date
from app.models.models import UserRole, StudentStatusEnum, PaymentMethod, AttendanceStatus, HomeworkStatus, LeadStatus

# Token Schemas
class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    user_id: int
    login_id: str
    role: UserRole
    full_name: str
    must_change_password: bool

class TokenPayload(BaseModel):
    sub: Optional[str] = None

class LoginRequest(BaseModel):
    login_id: str # 6 talik unikal raqam (masalan 100101)
    password: str

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

class LinkTelegramChatRequest(BaseModel):
    login_id: str
    chat_id: str

class TelegramLoginRequest(BaseModel):
    telegram_id: str

# User Schemas
class UserBase(BaseModel):
    full_name: str
    phone: str
    parent_phone: Optional[str] = None
    role: UserRole = UserRole.STUDENT
    student_status: StudentStatusEnum = StudentStatusEnum.ACTIVE
    telegram_chat_id: Optional[str] = None

class UserCreate(UserBase):
    login_id: Optional[str] = None # Admin kiritadi yoki avtomatik 6 talik generatsiya qilinadi
    password: Optional[str] = None # Vaqtinchalik parol (default: 123456)

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    parent_phone: Optional[str] = None
    role: Optional[UserRole] = None
    student_status: Optional[StudentStatusEnum] = None
    telegram_chat_id: Optional[str] = None
    is_active: Optional[bool] = None

class UserResponse(UserBase):
    id: int
    login_id: str
    is_active: bool
    is_password_changed: bool
    coins_balance: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# Room Schemas
class RoomBase(BaseModel):
    name: str
    capacity: int = 20
    description: Optional[str] = None

class RoomCreate(RoomBase):
    pass

class RoomUpdate(BaseModel):
    name: Optional[str] = None
    capacity: Optional[int] = None
    description: Optional[str] = None

class RoomResponse(RoomBase):
    id: int

    model_config = ConfigDict(from_attributes=True)

# Course Schemas
class CourseBase(BaseModel):
    title: str
    description: Optional[str] = None
    price_monthly: float
    duration_months: int = 3

class CourseCreate(CourseBase):
    pass

class CourseUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    price_monthly: Optional[float] = None
    duration_months: Optional[int] = None

class CourseResponse(CourseBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# Group Schemas
class GroupBase(BaseModel):
    name: str
    course_id: int
    teacher_id: int
    room_id: Optional[int] = None
    room_name: Optional[str] = None
    days_of_week: str  # e.g., "MON,WED,FRI"
    start_time: str   # e.g., "14:00"
    end_time: str     # e.g., "16:00"

class GroupCreate(GroupBase):
    pass

class GroupUpdate(BaseModel):
    name: Optional[str] = None
    course_id: Optional[int] = None
    teacher_id: Optional[int] = None
    room_id: Optional[int] = None
    room_name: Optional[str] = None
    days_of_week: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    is_active: Optional[bool] = None

class GroupResponse(BaseModel):
    id: int
    name: str
    course_id: int
    teacher_id: int
    room_id: Optional[int] = None
    days_of_week: str
    start_time: str
    end_time: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class GroupStudentItemResponse(UserResponse):
    discount_type: Optional[str] = "STANDARD"
    custom_price: Optional[float] = None
    discount_note: Optional[str] = None

class GroupDetailResponse(GroupResponse):
    course: Optional[CourseResponse] = None
    teacher: Optional[UserResponse] = None
    room: Optional[RoomResponse] = None
    students: List[GroupStudentItemResponse] = []

    model_config = ConfigDict(from_attributes=True)

# Lesson & Attendance Schemas
class LessonCreate(BaseModel):
    group_id: int
    lesson_date: date
    topic: Optional[str] = None
    room_id: Optional[int] = None

class LessonResponse(BaseModel):
    id: int
    group_id: int
    teacher_id: int
    room_id: int
    lesson_date: date
    topic: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class AttendanceItem(BaseModel):
    student_id: int
    status: AttendanceStatus # PRESENT, LATE, ABSENT, EXCUSED
    note: Optional[str] = None

class AttendanceBulkCreate(BaseModel):
    lesson_id: int
    attendances: List[AttendanceItem]

class AttendanceResponse(BaseModel):
    id: int
    lesson_id: int
    student_id: int
    status: AttendanceStatus
    note: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# Homework Schemas
class HomeworkCreate(BaseModel):
    group_id: int
    title: str
    description: Optional[str] = None
    pdf_file_url: Optional[str] = None
    max_coins: int = 10
    due_date: Optional[date] = None

class HomeworkResponse(BaseModel):
    id: int
    group_id: int
    teacher_id: int
    title: str
    description: Optional[str] = None
    pdf_file_url: Optional[str] = None
    max_coins: int
    due_date: Optional[date] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class HomeworkSubmissionCreate(BaseModel):
    homework_id: int
    text_submission: Optional[str] = None
    file_url: Optional[str] = None

class HomeworkSubmissionResponse(BaseModel):
    id: int
    homework_id: int
    student_id: int
    student_name: Optional[str] = None
    student_login_id: Optional[str] = None
    file_url: Optional[str] = None
    text_submission: Optional[str] = None
    grade: Optional[int] = None
    coins_awarded: int
    feedback: Optional[str] = None
    status: HomeworkStatus
    submitted_at: datetime

    model_config = ConfigDict(from_attributes=True)

class HomeworkGradeRequest(BaseModel):
    submission_id: int
    grade: int
    coins_awarded: int
    feedback: Optional[str] = None

# Payment & Expense Schemas
class PaymentCreate(BaseModel):
    student_id: int
    amount: float
    payment_method: PaymentMethod = PaymentMethod.CASH
    month_for: str
    discount_amount: float = 0.0
    note: Optional[str] = None

class PaymentUpdate(BaseModel):
    amount: Optional[float] = None
    payment_method: Optional[PaymentMethod] = None
    month_for: Optional[str] = None
    discount_amount: Optional[float] = None
    note: Optional[str] = None

class PaymentResponse(BaseModel):
    id: int
    student_id: int
    amount: float
    payment_method: PaymentMethod
    transaction_id: Optional[str] = None
    month_for: str
    discount_amount: float
    note: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ExpenseCreate(BaseModel):
    title: str
    amount: float
    category: str
    date: date
    description: Optional[str] = None

class ExpenseResponse(BaseModel):
    id: int
    title: str
    amount: float
    category: str
    date: date
    description: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# Lead Schemas
class LeadCreate(BaseModel):
    full_name: str
    phone: str
    course_id: Optional[int] = None
    notes: Optional[str] = None
    telegram_user_id: Optional[str] = None

class LeadStatusUpdate(BaseModel):
    status: LeadStatus
    notes: Optional[str] = None

class LeadResponse(BaseModel):
    id: int
    full_name: str
    phone: str
    course_id: Optional[int] = None
    status: LeadStatus
    telegram_user_id: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# Reward Schemas
class RewardItemCreate(BaseModel):
    title: str
    description: Optional[str] = None
    coin_price: int
    stock_quantity: int = 10

class RewardItemResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    coin_price: int
    stock_quantity: int
    is_active: bool

    model_config = ConfigDict(from_attributes=True)

class RewardRedeemRequest(BaseModel):
    reward_item_id: int

class RewardRedemptionResponse(BaseModel):
    id: int
    student_id: int
    reward_item_id: int
    coins_spent: int
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class RedemptionStatusUpdate(BaseModel):
    status: str # APPROVED, DELIVERED, REJECTED

class CoinTransactionResponse(BaseModel):
    id: int
    student_id: int
    amount: int
    reason: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# Teacher Payroll Schemas
class PayrollCalculateRequest(BaseModel):
    teacher_id: int
    month_for: str # e.g. "2026-08"
    percentage_rate: float = 40.0 # e.g. 40% of income generated by teacher's groups

class PayrollPayRequest(BaseModel):
    payroll_id: int
    amount: float
    note: Optional[str] = None

class TeacherPayrollResponse(BaseModel):
    id: int
    teacher_id: int
    month_for: str
    percentage_rate: float
    calculated_salary: float
    paid_amount: float
    status: str
    note: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# Billing & Debtors Schemas
class StudentBillingGenerateRequest(BaseModel):
    month_for: str # e.g. "2026-08"
    due_date: Optional[date] = None

class StudentBillingResponse(BaseModel):
    id: int
    student_id: int
    group_id: int
    month_for: str
    amount_due: float
    amount_paid: float
    is_paid: bool
    due_date: Optional[date] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class DebtorResponse(BaseModel):
    student_id: int
    student_name: str
    phone: str
    login_id: str
    total_debt: float
    unpaid_months: List[str]

class GroupAssignStudentRequest(BaseModel):
    custom_price: Optional[float] = None
    discount_type: Optional[str] = "STANDARD"  # STANDARD, GRANT_100, DISCOUNT_50, CHILD_TARIFF, ADULT_TARIFF, PRORATED, CUSTOM
    tariff_type: Optional[str] = None  # Frontend alias
    discount_note: Optional[str] = None

    def get_effective_discount_type(self) -> str:
        t = self.discount_type or self.tariff_type or "STANDARD"
        if t == "STANDART":
            return "STANDARD"
        return t

class StudentGroupCourseInfo(BaseModel):
    group_id: int
    group_name: str
    course_id: int
    course_title: str
    price_monthly: float
    effective_fee: Optional[float] = None
    discount_type: Optional[str] = "STANDARD"
    discount_note: Optional[str] = None


class StudentBillingInfoResponse(BaseModel):
    student_id: int
    student_name: str
    login_id: str
    phone: str
    telegram_chat_id: Optional[str] = None
    groups: List[StudentGroupCourseInfo]
    total_monthly_fee: float
    month_for: str
    month_amount_due: float
    month_amount_paid: float
    month_remaining_due: float
    month_surplus: float = 0.0
    past_debt: float = 0.0
    past_credit: float = 0.0
    total_debt: float
    total_credit: float
    net_balance: float

class PaymentRecordResult(BaseModel):
    message: str
    payment_id: int
    student_name: str
    amount_paid: float
    month_for: str
    total_due: float
    remaining_debt: float
    credit_amount: float
    telegram_notified: bool

# Question Schemas
class QuestionCreate(BaseModel):
    course_id: Optional[int] = None
    question_text: str
    correct_answer: str
    options: List[str]

class QuestionResponse(BaseModel):
    id: int
    course_id: Optional[int] = None
    course_title: Optional[str] = None
    created_by_id: int
    question_text: str
    correct_answer: str
    options: List[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class QuestionImportTextRequest(BaseModel):
    raw_text: str
    course_id: Optional[int] = None

# Exam & Exam Result Schemas
class ExamCreate(BaseModel):
    group_id: int
    title: str
    exam_type: str = "OFFLINE" # "ONLINE" or "OFFLINE"
    max_score: float = 100.0
    pass_score: float = 70.0
    duration_minutes: int = 30
    questions_data: Optional[str] = None
    exam_date: date

class ExamResponse(BaseModel):
    id: int
    group_id: int
    group_name: Optional[str] = None
    course_id: Optional[int] = None
    course_title: Optional[str] = None
    teacher_id: int
    teacher_name: Optional[str] = None
    title: str
    exam_type: str = "OFFLINE"
    status: str = "SCHEDULED" # "SCHEDULED", "ACTIVE", "COMPLETED"
    max_score: float
    pass_score: float = 70.0
    duration_minutes: int = 30
    questions_data: Optional[str] = None
    started_at: Optional[datetime] = None
    exam_date: date
    results_count: Optional[int] = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ExamSubmitRequest(BaseModel):
    answers: dict # { "0": "Selected option", ... }

class ExamResultItem(BaseModel):
    student_id: int
    score: float
    feedback: Optional[str] = None

class ExamResultBulkCreate(BaseModel):
    exam_id: int
    results: List[ExamResultItem]

class ExamResultResponse(BaseModel):
    id: int
    exam_id: int
    student_id: int
    student_name: Optional[str] = None
    student_login_id: Optional[str] = None
    score: float
    percentage: Optional[float] = None
    is_passed: Optional[bool] = False
    certificate_code: Optional[str] = None
    feedback: Optional[str] = None
    answers_data: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# Analytics & Leaderboard Schemas
class LeaderboardItem(BaseModel):
    rank: int
    student_id: int
    student_name: str
    coins_balance: int

class StudentAnalyticsResponse(BaseModel):
    student_id: int
    full_name: str
    total_lessons_attended: int
    attendance_rate_percentage: float
    homework_submissions_count: int
    coins_balance: int
    average_exam_score: float



# New Schemas for remaining models

class BranchBase(BaseModel):
    name: str
    address: Optional[str] = None
    phone: Optional[str] = None
    manager_name: Optional[str] = None
    is_active: bool = True

class BranchCreate(BranchBase):
    pass

class BranchResponse(BranchBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class CertificateCreate(BaseModel):
    certificate_code: str
    student_id: int
    course_id: int
    qr_hash: str
    issue_date: Optional[date] = None

class CertificateResponse(BaseModel):
    id: int
    certificate_code: str
    student_id: int
    student_name: Optional[str] = None
    student_login_id: Optional[str] = None
    course_id: int
    course_title: Optional[str] = None
    qr_hash: str
    issue_date: date
    model_config = ConfigDict(from_attributes=True)

class SupportTicketCreate(BaseModel):
    user_name: str
    user_phone: str
    message: str

class SupportTicketResponse(BaseModel):
    id: int
    user_id: Optional[int] = None
    user_name: str
    user_phone: str
    message: str
    status: str
    admin_reply: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class SupportTicketStatusUpdate(BaseModel):
    status: str
    admin_reply: Optional[str] = None

class AuditLogResponse(BaseModel):
    id: int
    user_id: Optional[int] = None
    action: str
    entity_name: str
    entity_id: Optional[int] = None
    details: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class StudentFreezeCreate(BaseModel):
    student_id: int
    start_date: date
    end_date: date
    reason: Optional[str] = None

class StudentFreezeResponse(BaseModel):
    id: int
    student_id: int
    start_date: date
    end_date: date
    reason: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class GroupTransferLogCreate(BaseModel):
    student_id: int
    old_group_id: int
    new_group_id: int
    reason: Optional[str] = None

class GroupTransferLogResponse(BaseModel):
    id: int
    student_id: int
    old_group_id: int
    new_group_id: int
    reason: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class WaitlistCreate(BaseModel):
    group_id: int
    student_id: int
    position: int = 1
    notes: Optional[str] = None

class WaitlistResponse(BaseModel):
    id: int
    group_id: int
    student_id: int
    position: int
    notes: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class CourseMaterialCreate(BaseModel):
    course_id: int
    group_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    pdf_file_url: str

class CourseMaterialResponse(BaseModel):
    id: int
    course_id: int
    group_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    pdf_file_url: str
    uploaded_by_id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class InvoiceCreate(BaseModel):
    invoice_number: str
    student_id: int
    amount: float
    due_date: date

class InvoiceResponse(BaseModel):
    id: int
    invoice_number: str
    student_id: int
    amount: float
    paid_amount: float
    status: str
    due_date: date
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class ParentStudentCreate(BaseModel):
    parent_id: int
    student_id: int
    relationship_type: str = "Parent"

class ParentStudentResponse(BaseModel):
    parent_id: int
    student_id: int
    relationship_type: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class TelegramNotificationLogResponse(BaseModel):
    id: int
    chat_id: str
    notification_type: str
    content: str
    status: str
    sent_at: datetime
    model_config = ConfigDict(from_attributes=True)

# =============================================
# TELEGRAM BOT API SCHEMAS
# =============================================
class TelegramStudentInfo(BaseModel):
    student_id: int
    full_name: str
    login_id: str
    phone: str
    group_name: Optional[str] = None
    course_title: Optional[str] = None
    days_of_week: Optional[str] = None
    start_time: Optional[str] = None
    student_status: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class TelegramPaymentItem(BaseModel):
    id: int
    amount: float
    payment_method: str
    month_for: str
    created_at: datetime
    note: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class TelegramPaymentHistory(BaseModel):
    student_id: int
    student_name: str
    login_id: str
    current_month: str
    monthly_fee: float
    month_amount_paid: float
    month_amount_due: float
    remaining: float
    is_paid: bool
    total_debt: float
    total_credit: float
    recent_payments: List[TelegramPaymentItem]
    model_config = ConfigDict(from_attributes=True)

class TelegramAttendanceStats(BaseModel):
    student_id: int
    student_name: str
    login_id: str
    group_name: Optional[str] = None
    course_title: Optional[str] = None
    days_of_week: Optional[str] = None
    current_month: str
    month_total: int = 0
    month_present: int = 0
    month_late: int = 0
    month_absent: int = 0
    month_excused: int = 0
    overall_total: int = 0
    overall_present: int = 0
    overall_late: int = 0
    overall_absent: int = 0
    overall_excused: int = 0
    model_config = ConfigDict(from_attributes=True)
