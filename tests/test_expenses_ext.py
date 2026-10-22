import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.main import app
from app.core.database import Base, get_db
from app.core.security import get_password_hash
from app.models.models import User, UserRole, Expense
from sqlalchemy import select

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
            is_password_changed=True,
            role=UserRole.ADMIN
        )
        teacher = User(
            login_id="200201",
            full_name="Akmal Karimov",
            phone="+998909998877",
            hashed_password=get_password_hash("teacher123"),
            is_password_changed=True,
            role=UserRole.TEACHER
        )
        session.add_all([admin, teacher])
        await session.commit()
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.pop(get_db, None)

@pytest.mark.asyncio
async def test_expense_employee_and_payment_method():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login_res = await ac.post("/api/v1/auth/login", json={
            "login_id": "777777",
            "password": "superadmin123"
        })
        assert login_res.status_code == 200
        headers = {"Authorization": f"Bearer {login_res.json()['access_token']}"}

        # 1. Xarajat yaratish (Karta + Xodim tanlangan)
        exp_res = await ac.post("/api/v1/finance/expenses", headers=headers, json={
            "title": "Akmal aka avans maoshi",
            "amount": 2000000.0,
            "category": "O'qituvchi Maoshi",
            "date": "2026-10-15",
            "description": "Karta orqali avans",
            "employee_id": 2,  # Teacher ID
            "payment_method": "CARD"
        })
        assert exp_res.status_code == 200
        data = exp_res.json()
        assert data["payment_method"] == "CARD"
        assert data["employee_id"] == 2
        assert data["employee_name"] == "Akmal Karimov"

        # 2. Xarajat yaratish (Naqd + Xodimsiz umumiy)
        exp_res2 = await ac.post("/api/v1/finance/expenses", headers=headers, json={
            "title": "Kanselyariya qog'ozi",
            "amount": 150000.0,
            "category": "Kanselyariya & Jihozlar",
            "date": "2026-10-16",
            "description": "Naqd to'landi",
            "employee_id": None,
            "payment_method": "CASH"
        })
        assert exp_res2.status_code == 200
        data2 = exp_res2.json()
        assert data2["payment_method"] == "CASH"
        assert data2["employee_id"] is None
        assert data2["employee_name"] is None

        # 3. Filtrlash testi: payment_method=CARD
        card_res = await ac.get("/api/v1/finance/expenses?payment_method=CARD", headers=headers)
        assert card_res.status_code == 200
        card_data = card_res.json()
        assert len(card_data) == 1
        assert card_data[0]["payment_method"] == "CARD"

        # 4. Filtrlash testi: employee_id=2
        emp_res = await ac.get("/api/v1/finance/expenses?employee_id=2", headers=headers)
        assert emp_res.status_code == 200
        emp_data = emp_res.json()
        assert len(emp_data) == 1
        assert emp_data[0]["employee_name"] == "Akmal Karimov"
