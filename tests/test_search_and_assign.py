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
        super_admin = User(
            login_id="777777",
            full_name="Super Admin",
            phone="+998907777777",
            hashed_password=get_password_hash("superadmin123"),
            is_password_changed=True,
            role=UserRole.ADMIN
        )
        teacher_user = User(
            login_id="200201",
            full_name="Akmal Karimov",
            phone="+998909998877",
            hashed_password=get_password_hash("teacher123"),
            is_password_changed=True,
            role=UserRole.TEACHER
        )
        student_133038 = User(
            login_id="133038",
            full_name="Jasurbek Aliyev",
            phone="+998901234567",
            parent_phone="+998907654321",
            hashed_password=get_password_hash("123456"),
            role=UserRole.STUDENT,
            is_active=True
        )
        room = Room(name="1-xona", capacity=20)
        c1 = Course(title="Matematika Kursi", price_monthly=450000.0)
        c2 = Course(title="Ingliz Tili Kursi", price_monthly=500000.0)

        session.add_all([super_admin, teacher_user, student_133038, room, c1, c2])
        await session.commit()
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.pop(get_db, None)

@pytest.mark.asyncio
async def test_search_and_exact_match():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login_res = await ac.post("/api/v1/auth/login", json={
            "login_id": "777777",
            "password": "superadmin123"
        })
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1-Test: ID bo'yicha qidiruv (133038)
        res_id = await ac.get("/api/v1/users/?role=STUDENT&search=133038", headers=headers)
        assert res_id.status_code == 200
        data_id = res_id.json()
        assert len(data_id) >= 1
        assert data_id[0]["login_id"] == "133038"

        # 2-Test: Ism bo'yicha qidiruv (Jasurbek)
        res_name = await ac.get("/api/v1/users/?role=STUDENT&search=Jasurbek", headers=headers)
        assert res_name.status_code == 200
        data_name = res_name.json()
        assert any(u["login_id"] == "133038" for u in data_name)

        # 3-Test: Telefon bo'yicha qidiruv (901234567)
        res_phone = await ac.get("/api/v1/users/?role=STUDENT&search=901234567", headers=headers)
        assert res_phone.status_code == 200
        data_phone = res_phone.json()
        assert any(u["login_id"] == "133038" for u in data_phone)

@pytest.mark.asyncio
async def test_multi_course_group_membership():
    """Bitta o'quvchi boshqa fandagi guruhga muvaffaqiyatli a'zo bo'la olishi testi"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login_res = await ac.post("/api/v1/auth/login", json={
            "login_id": "777777",
            "password": "superadmin123"
        })
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        async with TestingSessionLocal() as session:
            teacher_res = await session.execute(select(User).where(User.role == UserRole.TEACHER))
            teacher = teacher_res.scalars().first()
            room_res = await session.execute(select(Room))
            room = room_res.scalars().first()
            c_res = await session.execute(select(Course))
            courses = c_res.scalars().all()
            c1, c2 = courses[0], courses[1]

            g1 = Group(name="Math-G1", course_id=c1.id, teacher_id=teacher.id, room_id=room.id, days_of_week="DUSH-CHOR-JUMA", start_time="08:00", end_time="10:00")
            g2 = Group(name="English-G2", course_id=c2.id, teacher_id=teacher.id, room_id=room.id, days_of_week="SESH-PAY-SHAN", start_time="10:00", end_time="12:00")
            session.add_all([g1, g2])
            await session.commit()
            await session.refresh(g1)
            await session.refresh(g2)

            st_res = await session.execute(select(User).where(User.login_id == "133038"))
            st = st_res.scalar_one()

        # 1-guruhga (Matematika) qo'shish
        res1 = await ac.post(f"/api/v1/groups/{g1.id}/students/{st.id}", headers=headers, json={"tariff_type": "STANDARD"})
        assert res1.status_code == 200

        # 2-guruhga (Ingliz tili - boshqa fan) qo'shish
        res2 = await ac.post(f"/api/v1/groups/{g2.id}/students/{st.id}", headers=headers, json={"tariff_type": "STANDARD"})
        assert res2.status_code == 200

        # Billing info: ikkala kurs ham borligini va summalar to'g'ri hisoblanganini tekshirish
        billing_res = await ac.get(f"/api/v1/finance/student/{st.id}/billing-info", headers=headers)
        assert billing_res.status_code == 200
        b_data = billing_res.json()
        assert len(b_data["groups"]) == 2
        assert b_data["total_monthly_fee"] == 950000.0  # 450,000 + 500,000
