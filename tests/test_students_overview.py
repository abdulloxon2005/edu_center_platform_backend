import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.main import app
from app.core.database import Base, get_db
from app.core.security import get_password_hash
from app.models.models import User, UserRole, Group, Course, Room, GroupStudent
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
        admin = User(login_id="777777", full_name="Super Admin", phone="+998907777777", hashed_password=get_password_hash("superadmin123"), role=UserRole.ADMIN)
        teacher = User(login_id="200201", full_name="Akmal Karimov", phone="+998909998877", hashed_password=get_password_hash("teacher123"), role=UserRole.TEACHER)
        st = User(login_id="133038", full_name="Jasurbek Aliyev", phone="+998901234567", hashed_password=get_password_hash("123456"), role=UserRole.STUDENT)
        room = Room(name="1-xona", capacity=20)
        c = Course(title="Ingliz Tili", price_monthly=400000.0)

        session.add_all([admin, teacher, st, room, c])
        await session.commit()
        await session.refresh(teacher)
        await session.refresh(st)
        await session.refresh(room)
        await session.refresh(c)

        g = Group(name="English-A1", course_id=c.id, teacher_id=teacher.id, room_id=room.id, days_of_week="DUSH-CHOR-JUMA", start_time="14:00", end_time="16:00")
        session.add(g)
        await session.commit()
        await session.refresh(g)

        gs = GroupStudent(group_id=g.id, student_id=st.id, is_active=True)
        session.add(gs)
        await session.commit()

    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.pop(get_db, None)

@pytest.mark.asyncio
async def test_students_overview_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login_res = await ac.post("/api/v1/auth/login", json={
            "login_id": "777777",
            "password": "superadmin123"
        })
        assert login_res.status_code == 200
        headers = {"Authorization": f"Bearer {login_res.json()['access_token']}"}

        # 1. Barcha o'quvchilar ro'yxati
        res = await ac.get("/api/v1/users/students-overview", headers=headers)
        print("422 detail:", res.status_code, res.text)
        assert res.status_code == 200
        data = res.json()
        assert len(data) >= 1
        st = data[0]
        assert st["login_id"] == "133038"
        assert st["full_name"] == "Jasurbek Aliyev"
        assert len(st["groups"]) == 1
        assert st["groups"][0]["group_name"] == "English-A1"
        assert st["groups"][0]["course_title"] == "Ingliz Tili"
        assert st["total_monthly_fee"] == 400000.0

        # 2. Qidiruv testi (search=133038)
        search_res = await ac.get("/api/v1/users/students-overview?search=133038", headers=headers)
        assert search_res.status_code == 200
        assert len(search_res.json()) == 1
