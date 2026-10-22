import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.main import app
from app.core.database import Base, get_db
from app.core.security import get_password_hash
from app.models.models import User, UserRole, Course

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
        c1 = Course(title="Ingliz Tili", price_monthly=450000.0, is_active=True)
        c2 = Course(title="Matematika", price_monthly=400000.0, is_active=True)
        session.add_all([admin, c1, c2])
        await session.commit()

    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_public_courses_access_no_auth():
    """Mijozlar ro'yxatdan o'tmasdan kurslar ro'yxatini yuklay olishi kerak"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/courses/")
        assert res.status_code == 200
        courses = res.json()
        assert len(courses) == 2
        titles = [c["title"] for c in courses]
        assert "Ingliz Tili" in titles


@pytest.mark.asyncio
async def test_public_lead_submission_success():
    """Saytdagi bepul konsultatsiya arizasi muvaffaqiyatli qabul qilinishi kerak"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/api/v1/crm/leads", json={
            "full_name": "Sardor Rahimov",
            "phone": "+998 90 987 65 43",
            "course_id": 1,
            "notes": "Bepul konsultatsiya so'rovi (saytdan)"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["id"] > 0
        assert data["full_name"] == "Sardor Rahimov"
        assert data["status"] == "NEW"


@pytest.mark.asyncio
async def test_cors_headers_support():
    """Turli domenlar va portlar (3000, 5173) uchun CORS to'g'ri ishlashi kerak"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.options("/api/v1/courses/", headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "GET"
        })
        assert res.status_code == 200
        assert "access-control-allow-origin" in res.headers
        assert res.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
