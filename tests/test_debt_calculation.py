import pytest
import pytest_asyncio
from datetime import date
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.main import app
from app.core.database import Base, get_db
from app.core.security import get_password_hash
from app.models.models import User, UserRole, Group, Course, Room, GroupStudent, Payment, PaymentMethod
from app.services.debt_service import (
    calculate_student_debt,
    calculate_batch_students_debt,
    calculate_student_effective_fee,
    DEBT_SYSTEM_START_MONTH
)

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestingSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)

async def override_get_db():
    async with TestingSessionLocal() as session:
        yield session

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    app.dependency_overrides[get_db] = override_get_db
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestingSessionLocal() as session:
        admin = User(
            login_id="777777",
            full_name="Super Admin",
            phone="+998907777777",
            hashed_password=get_password_hash("superadmin123"),
            role=UserRole.ADMIN
        )
        teacher = User(
            login_id="200201",
            full_name="Oqil O'qituvchi",
            phone="+998909998877",
            hashed_password=get_password_hash("teacher123"),
            role=UserRole.TEACHER
        )
        # Student 1: regular student
        st1 = User(
            login_id="100001",
            full_name="Vali Normatov",
            phone="+998901111111",
            hashed_password=get_password_hash("123456"),
            role=UserRole.STUDENT
        )
        # Student 2: student with grant
        st2 = User(
            login_id="100002",
            full_name="Zilola Umarova",
            phone="+998902222222",
            hashed_password=get_password_hash("123456"),
            role=UserRole.STUDENT
        )
        room = Room(name="Asosiy Xona", capacity=25)
        c1 = Course(title="Matematika", price_monthly=500000.0)
        c2 = Course(title="Fizika", price_monthly=400000.0)

        session.add_all([admin, teacher, st1, st2, room, c1, c2])
        await session.commit()
        await session.refresh(teacher)
        await session.refresh(st1)
        await session.refresh(st2)
        await session.refresh(room)
        await session.refresh(c1)
        await session.refresh(c2)

        g1 = Group(name="Math-Pro", course_id=c1.id, teacher_id=teacher.id, room_id=room.id, days_of_week="DUSH-CHOR-JUMA", start_time="10:00", end_time="12:00")
        g2 = Group(name="Phys-01", course_id=c2.id, teacher_id=teacher.id, room_id=room.id, days_of_week="SESH-PAY-SHAN", start_time="14:00", end_time="16:00")
        session.add_all([g1, g2])
        await session.commit()
        await session.refresh(g1)
        await session.refresh(g2)

        # Vali is in Math (500k)
        gs1 = GroupStudent(group_id=g1.id, student_id=st1.id, is_active=True)
        # Zilola is in Math with 100% Grant
        gs2 = GroupStudent(group_id=g1.id, student_id=st2.id, is_active=True, discount_type="GRANT_100")
        session.add_all([gs1, gs2])
        await session.commit()

    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_pre_october_zero_debt():
    """2026-10 dan oldingi davrlar (masalan, 2026-08, 2026-09) qarzdorlik hisobiga kirmaydi (qarz = 0)"""
    async with TestingSessionLocal() as session:
        # Vali 2026-08 da to'lov qilmagan bo'lsa ham
        res_aug = await calculate_student_debt(session, student_id=3, month_for="2026-08")
        assert res_aug.debt == 0.0
        assert res_aug.is_paid == True
        assert res_aug.is_debtor == False

        res_sep = await calculate_student_debt(session, student_id=3, month_for="2026-09")
        assert res_sep.debt == 0.0
        assert res_sep.is_debtor == False


@pytest.mark.asyncio
async def test_october_single_month_debt():
    """2026-10 (oktabr) oyida qat'iy 1 oylik qarz hisoblanishi kerak (500,000 UZS)"""
    async with TestingSessionLocal() as session:
        res_oct = await calculate_student_debt(session, student_id=3, month_for="2026-10")
        assert res_oct.total_monthly_fee == 500000.0
        assert res_oct.amount_paid == 0.0
        assert res_oct.debt == 500000.0
        assert res_oct.is_debtor == True
        assert res_oct.is_paid == False


@pytest.mark.asyncio
async def test_partial_and_full_payment():
    """Qisman va to'liq to'lov holatlarida 1 oylik qoldiq to'g'ri hisoblanishi"""
    async with TestingSessionLocal() as session:
        # 1. 200,000 UZS qisman to'lov
        p1 = Payment(
            student_id=3,
            amount=200000.0,
            payment_method=PaymentMethod.CASH,
            month_for="2026-10"
        )
        session.add(p1)
        await session.commit()

        res_partial = await calculate_student_debt(session, student_id=3, month_for="2026-10")
        assert res_partial.amount_paid == 200000.0
        assert res_partial.debt == 300000.0
        assert res_partial.credit == 0.0
        assert res_partial.is_debtor == True

        # 2. Qolgan 300,000 UZS to'liq to'langanda
        p2 = Payment(
            student_id=3,
            amount=300000.0,
            payment_method=PaymentMethod.CARD,
            month_for="2026-10"
        )
        session.add(p2)
        await session.commit()

        res_full = await calculate_student_debt(session, student_id=3, month_for="2026-10")
        assert res_full.amount_paid == 500000.0
        assert res_full.debt == 0.0
        assert res_full.credit == 0.0
        assert res_full.is_paid == True
        assert res_full.is_debtor == False


@pytest.mark.asyncio
async def test_grant_student_has_zero_debt():
    """100% grant olgan o'quvchi qarzdor bo'lmasligi kerak"""
    async with TestingSessionLocal() as session:
        res = await calculate_student_debt(session, student_id=4, month_for="2026-10")
        assert res.total_monthly_fee == 0.0
        assert res.debt == 0.0
        assert res.is_debtor == False


@pytest.mark.asyncio
async def test_inactive_enrollment_does_not_accrue_debt():
    """Nofaol (is_active == False) guruh a'zoligi uchun qarz hisoblanmasligi kerak"""
    async with TestingSessionLocal() as session:
        # Vali uchun guruh a'zoligini nofaol qilamiz
        gs = (await session.execute(GroupStudent.__table__.select().where(GroupStudent.student_id == 3))).first()
        from sqlalchemy import update
        await session.execute(update(GroupStudent).where(GroupStudent.student_id == 3).values(is_active=False))
        await session.commit()

        res = await calculate_student_debt(session, student_id=3, month_for="2026-10")
        assert res.total_monthly_fee == 0.0
        assert res.debt == 0.0
        assert res.is_debtor == False


@pytest.mark.asyncio
async def test_api_debtors_and_billing_info():
    """API orqali qarzdorlar ro'yxati va billing info tekshiruvi"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login_res = await ac.post("/api/v1/auth/login", json={
            "login_id": "777777",
            "password": "superadmin123"
        })
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1. 2026-09 oyi uchun debtors bo'sh bo'lishi kerak (pre-October)
        res_sep = await ac.get("/api/v1/finance/debtors?month_for=2026-09", headers=headers)
        assert res_sep.status_code == 200
        assert len(res_sep.json()) == 0

        # 2. 2026-10 oyi uchun Vali qarzdor sifatida chiqishi kerak
        res_oct = await ac.get("/api/v1/finance/debtors?month_for=2026-10", headers=headers)
        assert res_oct.status_code == 200
        debtors = res_oct.json()
        assert len(debtors) == 1
        assert debtors[0]["student_id"] == 3
        assert debtors[0]["total_debt"] == 500000.0
        assert debtors[0]["unpaid_months"] == ["2026-10"]

        # 3. Student billing info: faqat 1 oylik qarz
        b_res = await ac.get("/api/v1/finance/student/3/billing-info?month_for=2026-10", headers=headers)
        assert b_res.status_code == 200
        b_data = b_res.json()
        assert b_data["total_monthly_fee"] == 500000.0
        assert b_data["total_debt"] == 500000.0
        assert b_data["past_debt"] == 0.0
        assert b_data["month_remaining_due"] == 500000.0
