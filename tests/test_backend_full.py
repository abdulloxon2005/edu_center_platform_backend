import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.main import app
from app.core.database import Base, get_db
from app.core.security import get_password_hash
from app.models.models import User, UserRole, Room, Course

# Test SQLite in-memory database
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestingSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)

async def override_get_db():
    async with TestingSessionLocal() as session:
        yield session

app.dependency_overrides[get_db] = override_get_db

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Seed Test Data
    async with TestingSessionLocal() as session:
        # Super Admin
        super_admin = User(
            login_id="777777",
            full_name="Super Admin",
            phone="+998907777777",
            hashed_password=get_password_hash("superadmin123"),
            is_password_changed=True,
            role=UserRole.ADMIN
        )
        # Bosh Admin
        admin_user = User(
            login_id="100000",
            full_name="Bosh Admin",
            phone="+998901234567",
            hashed_password=get_password_hash("admin123"),
            is_password_changed=True,
            role=UserRole.ADMIN
        )
        # O'quvchi (Ali Valiyev)
        student_user = User(
            login_id="100101",
            full_name="Ali Valiyev",
            phone="+998901234568",
            hashed_password=get_password_hash("Ali"),
            is_password_changed=False,
            role=UserRole.STUDENT,
            coins_balance=50
        )
        # O'qituvchi (Ustoz Akmal)
        teacher_user = User(
            login_id="200201",
            full_name="Akmal Karimov",
            phone="+998909998877",
            hashed_password=get_password_hash("teacher123"),
            is_password_changed=True,
            role=UserRole.TEACHER
        )
        # Dars xonasi
        room = Room(name="1-xonasi (IT Lab)", capacity=15, description="Kompyuter sinfi")

        # Kurs
        course = Course(title="Python Backend", description="FastAPI & Django", price_monthly=600000.0, duration_months=4)

        session.add_all([super_admin, admin_user, student_user, teacher_user, room, course])
        await session.commit()
        
    yield
    
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

# ----------------------------------------------------
# 1. AUTHENTICATION & AUTHORIZATION TESTS
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_01_super_admin_login():
    """1. Super Admin (777777) login va JWT token testi"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/v1/auth/login", json={
            "login_id": "777777",
            "password": "superadmin123"
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["role"] == "ADMIN"
        assert data["login_id"] == "777777"
        assert data["must_change_password"] is False

@pytest.mark.asyncio
async def test_02_student_temporary_password_login():
    """2. O'quvchi (100101) vaqtinchalik parol 'Ali' bilan kirishi va must_change_password testi"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/v1/auth/login", json={
            "login_id": "100101",
            "password": "Ali"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["role"] == "STUDENT"
        assert data["must_change_password"] is True

@pytest.mark.asyncio
async def test_03_change_password_and_login_new_pass():
    """3. Parol o'zgartirish va yangi parol bilan tizimga kirish testi"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Login with temp pass
        login_res = await ac.post("/api/v1/auth/login", json={"login_id": "100101", "password": "Ali"})
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Change password
        ch_res = await ac.post("/api/v1/auth/change-password", json={
            "old_password": "Ali",
            "new_password": "NewPassword123"
        }, headers=headers)
        assert ch_res.status_code == 200

        # Login with new password
        login2_res = await ac.post("/api/v1/auth/login", json={"login_id": "100101", "password": "NewPassword123"})
        assert login2_res.status_code == 200
        assert login2_res.json()["must_change_password"] is False


@pytest.mark.asyncio
async def test_04_invalid_login_and_unauthorized_access():
    """4. Noto'g'ri login/parol va ruxsatsiz so'rovlar holati"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Wrong pass
        res1 = await ac.post("/api/v1/auth/login", json={"login_id": "100101", "password": "WrongPassword"})
        assert res1.status_code == 401

        # Protected route without token
        res2 = await ac.get("/api/v1/users/")
        assert res2.status_code == 401

@pytest.mark.asyncio
async def test_05_link_telegram_parent_chat():
    """5. Telegram Bot orqali 6 talik login_id (100101) ota-ona telegram_chat_id siga bog'lash testi"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/v1/auth/link-telegram", json={
            "login_id": "100101",
            "chat_id": "987654321"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["student_name"] == "Ali Valiyev"

# ----------------------------------------------------
# 2. USER MANAGEMENT TESTS
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_06_user_crud_operations():
    """6. Foydalanuvchilar Yaratish, Ro'yxat, Olish, Yangilash va O'chirish (CRUD)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        admin_login = await ac.post("/api/v1/auth/login", json={"login_id": "777777", "password": "superadmin123"})
        headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

        # Create Student
        create_res = await ac.post("/api/v1/users/", json={
            "full_name": "Sardor Raimov",
            "phone": "+998911234567",
            "role": "STUDENT"
        }, headers=headers)
        assert create_res.status_code == 200
        user_data = create_res.json()
        user_id = user_data["id"]
        assert len(user_data["login_id"]) == 6

        # Get User by ID
        get_res = await ac.get(f"/api/v1/users/{user_id}", headers=headers)
        assert get_res.status_code == 200
        assert get_res.json()["full_name"] == "Sardor Raimov"

        # Update User
        put_res = await ac.put(f"/api/v1/users/{user_id}", json={"full_name": "Sardorbek Raimov"}, headers=headers)
        assert put_res.status_code == 200
        assert put_res.json()["full_name"] == "Sardorbek Raimov"

        # List Users filtered by role
        list_res = await ac.get("/api/v1/users/?role=STUDENT", headers=headers)
        assert list_res.status_code == 200
        assert len(list_res.json()) >= 2

        # Delete User (Deactivate)
        del_res = await ac.delete(f"/api/v1/users/{user_id}", headers=headers)
        assert del_res.status_code == 200

# ----------------------------------------------------
# 3. COURSES & ROOMS TESTS
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_07_courses_and_rooms_crud():
    """7. Kurslar va Dars Xonalari CRUD operatsiyalari"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        admin_login = await ac.post("/api/v1/auth/login", json={"login_id": "777777", "password": "superadmin123"})
        headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

        # Create Course
        c_res = await ac.post("/api/v1/courses/", json={
            "title": "General English IELTS",
            "description": "Intensive English",
            "price_monthly": 500000.0,
            "duration_months": 3
        }, headers=headers)
        assert c_res.status_code == 200
        course_id = c_res.json()["id"]

        # List Courses
        clist_res = await ac.get("/api/v1/courses/", headers=headers)
        assert clist_res.status_code == 200
        assert len(clist_res.json()) >= 2

        # Create Room
        r_res = await ac.post("/api/v1/courses/rooms", json={
            "name": "2-xona (Kompyuter sinfi)",
            "capacity": 20
        }, headers=headers)
        assert r_res.status_code == 200
        room_id = r_res.json()["id"]

        # Update Room
        u_room = await ac.put(f"/api/v1/courses/rooms/{room_id}", json={"capacity": 25}, headers=headers)
        assert u_room.status_code == 200
        assert u_room.json()["capacity"] == 25

# ----------------------------------------------------
# 4. GROUPS & SCHEDULE CONFLICT SOLVER TESTS
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_08_group_creation_and_schedule_conflict():
    """8. Guruh yaratish, Xona va O'qituvchi dars jadvali konfliktlarini aniqlash testi"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        admin_login = await ac.post("/api/v1/auth/login", json={"login_id": "777777", "password": "superadmin123"})
        headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

        # Fetch course, teacher (200201), room (1)
        courses = (await ac.get("/api/v1/courses/", headers=headers)).json()
        rooms = (await ac.get("/api/v1/courses/rooms", headers=headers)).json()
        users = (await ac.get("/api/v1/users/?role=TEACHER", headers=headers)).json()

        course_id = courses[0]["id"]
        room_id = rooms[0]["id"]
        teacher_id = users[0]["id"]

        # 1. Group 1 creation (MON,WED,FRI 14:00-16:00)
        g1_res = await ac.post("/api/v1/groups/", json={
            "name": "Python Backend - Group 1",
            "course_id": course_id,
            "teacher_id": teacher_id,
            "room_id": room_id,
            "days_of_week": "MON,WED,FRI",
            "start_time": "14:00",
            "end_time": "16:00"
        }, headers=headers)
        assert g1_res.status_code == 200
        group1_id = g1_res.json()["id"]

        # 2. Try creating Group 2 in SAME ROOM at overlapping time (15:00-17:00) -> Conflict expected!
        g2_res = await ac.post("/api/v1/groups/", json={
            "name": "Python Backend - Group 2",
            "course_id": course_id,
            "teacher_id": teacher_id,
            "room_id": room_id,
            "days_of_week": "MON,WED",
            "start_time": "15:00",
            "end_time": "17:00"
        }, headers=headers)
        assert g2_res.status_code == 400
        assert "KONFLIKTI" in g2_res.json()["detail"]

        # 3. Create Group 2 at non-overlapping time (16:00-18:00) -> Success!
        g3_res = await ac.post("/api/v1/groups/", json={
            "name": "Python Backend - Group 2",
            "course_id": course_id,
            "teacher_id": teacher_id,
            "room_id": room_id,
            "days_of_week": "MON,WED,FRI",
            "start_time": "16:00",
            "end_time": "18:00"
        }, headers=headers)
        assert g3_res.status_code == 200

        # 4. Assign Student (100101) to Group 1
        students = (await ac.get("/api/v1/users/?role=STUDENT", headers=headers)).json()
        student_id = students[0]["id"]

        assign_res = await ac.post(f"/api/v1/groups/{group1_id}/students/{student_id}", headers=headers)
        assert assign_res.status_code == 200

        # 5. Get Group Details
        detail_res = await ac.get(f"/api/v1/groups/{group1_id}", headers=headers)
        assert detail_res.status_code == 200
        assert len(detail_res.json()["students"]) == 1

# ----------------------------------------------------
# 5. LESSONS & ATTENDANCE TESTS
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_09_lessons_and_attendance_marking():
    """9. Dars yaratish, Yo'qlama qilish va davomat tarixini olish testi"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        admin_login = await ac.post("/api/v1/auth/login", json={"login_id": "777777", "password": "superadmin123"})
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

        # Create group and assign student
        courses = (await ac.get("/api/v1/courses/", headers=admin_headers)).json()
        rooms = (await ac.get("/api/v1/courses/rooms", headers=admin_headers)).json()
        teachers = (await ac.get("/api/v1/users/?role=TEACHER", headers=admin_headers)).json()
        students = (await ac.get("/api/v1/users/?role=STUDENT", headers=admin_headers)).json()

        g_res = await ac.post("/api/v1/groups/", json={
            "name": "IELTS Standard Group",
            "course_id": courses[0]["id"],
            "teacher_id": teachers[0]["id"],
            "room_id": rooms[0]["id"],
            "days_of_week": "TUE,THU,SAT",
            "start_time": "10:00",
            "end_time": "12:00"
        }, headers=admin_headers)
        group_id = g_res.json()["id"]

        await ac.post(f"/api/v1/groups/{group_id}/students/{students[0]['id']}", headers=admin_headers)

        # Login as Teacher (200201 / teacher123)
        t_login = await ac.post("/api/v1/auth/login", json={"login_id": "200201", "password": "teacher123"})
        teacher_headers = {"Authorization": f"Bearer {t_login.json()['access_token']}"}

        # Teacher creates Lesson
        l_res = await ac.post("/api/v1/attendance/lessons", json={
            "group_id": group_id,
            "lesson_date": "2026-08-08",
            "topic": "Python Asyncio & SQLAlchemy 2.0"
        }, headers=teacher_headers)
        assert l_res.status_code == 200
        lesson_id = l_res.json()["id"]

        # Teacher marks attendance
        att_res = await ac.post("/api/v1/attendance/mark", json={
            "lesson_id": lesson_id,
            "attendances": [
                {
                    "student_id": students[0]["id"],
                    "status": "PRESENT",
                    "note": "A'lo qatnashdi"
                }
            ]
        }, headers=teacher_headers)
        assert att_res.status_code == 200

        # View student attendance history
        hist_res = await ac.get(f"/api/v1/attendance/student/{students[0]['id']}", headers=teacher_headers)
        assert hist_res.status_code == 200
        assert len(hist_res.json()) == 1

# ----------------------------------------------------
# 6. HOMEWORK & SUBMISSIONS & GRADING TESTS
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_10_homework_workflow_and_coins():
    """10. Uy vazifasi berish, topshirish, baholash va tanga mukofoti berish testi"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        admin_login = await ac.post("/api/v1/auth/login", json={"login_id": "777777", "password": "superadmin123"})
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

        courses = (await ac.get("/api/v1/courses/", headers=admin_headers)).json()
        rooms = (await ac.get("/api/v1/courses/rooms", headers=admin_headers)).json()
        teachers = (await ac.get("/api/v1/users/?role=TEACHER", headers=admin_headers)).json()
        students = (await ac.get("/api/v1/users/?role=STUDENT", headers=admin_headers)).json()

        g_res = await ac.post("/api/v1/groups/", json={
            "name": "Fullstack Group",
            "course_id": courses[0]["id"],
            "teacher_id": teachers[0]["id"],
            "room_id": rooms[0]["id"],
            "days_of_week": "MON,WED,FRI",
            "start_time": "18:00",
            "end_time": "20:00"
        }, headers=admin_headers)
        group_id = g_res.json()["id"]

        # Login Teacher
        t_login = await ac.post("/api/v1/auth/login", json={"login_id": "200201", "password": "teacher123"})
        t_headers = {"Authorization": f"Bearer {t_login.json()['access_token']}"}

        # Create Homework
        hw_res = await ac.post("/api/v1/homework/", data={
            "group_id": group_id,
            "title": "FastAPI Async Endpoints Write-up",
            "description": "Write async CRUD endpoints",
            "max_coins": 15
        }, headers=t_headers)
        assert hw_res.status_code == 200
        hw_id = hw_res.json()["id"]

        # Student Login (100101 / Ali)
        s_login = await ac.post("/api/v1/auth/login", json={"login_id": "100101", "password": "Ali"})
        s_headers = {"Authorization": f"Bearer {s_login.json()['access_token']}"}

        # Student submits homework
        sub_res = await ac.post("/api/v1/homework/submit", data={
            "homework_id": hw_id,
            "text_submission": "GitHub repo link: https://github.com/test/repo"
        }, headers=s_headers)
        assert sub_res.status_code == 200
        submission_id = sub_res.json()["submission_id"]

        # Teacher grades homework and awards 15 coins
        grade_res = await ac.post("/api/v1/homework/grade", json={
            "submission_id": submission_id,
            "grade": 100,
            "coins_awarded": 15,
            "feedback": "Barakalla, ideal koding!"
        }, headers=t_headers)
        assert grade_res.status_code == 200

        # Verify Student Coin balance increased (50 + 15 = 65)
        me_res = await ac.get("/api/v1/auth/me", headers=s_headers)
        assert me_res.json()["coins_balance"] == 65

# ----------------------------------------------------
# 7. GAMIFICATION & REWARD SHOP TESTS
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_11_gamification_reward_shop():
    """11. Tangalar evaziga sovg'alar do'koni va harid (Redeem) testi"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        admin_login = await ac.post("/api/v1/auth/login", json={"login_id": "777777", "password": "superadmin123"})
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

        # Admin creates Reward Item
        item_res = await ac.post("/api/v1/gamification/items", json={
            "title": "Smart Brelok & Notebook",
            "description": "Markaz brendi tushirilgan blknot",
            "coin_price": 30,
            "stock_quantity": 5
        }, headers=admin_headers)
        assert item_res.status_code == 200
        item_id = item_res.json()["id"]

        # Student Login (100101 has 50 coins)
        s_login = await ac.post("/api/v1/auth/login", json={"login_id": "100101", "password": "Ali"})
        s_headers = {"Authorization": f"Bearer {s_login.json()['access_token']}"}

        # Redeem Reward Item
        red_res = await ac.post("/api/v1/gamification/redeem", json={"reward_item_id": item_id}, headers=s_headers)
        assert red_res.status_code == 200
        assert "Tabriklaymiz" in red_res.json()["message"]

        # Check balance reduced (50 - 30 = 20)
        me_res = await ac.get("/api/v1/auth/me", headers=s_headers)
        assert me_res.json()["coins_balance"] == 20

# ----------------------------------------------------
# 8. FINANCE & DASHBOARD STATS TESTS
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_12_finance_and_dashboard():
    """12. To'lovlar, Xarajatlar va Kassa Dashbord statistikasi testi"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        admin_login = await ac.post("/api/v1/auth/login", json={"login_id": "777777", "password": "superadmin123"})
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

        students = (await ac.get("/api/v1/users/?role=STUDENT", headers=admin_headers)).json()
        student_id = students[0]["id"]

        # 1. Record Payment (600,000 UZS)
        p_res = await ac.post("/api/v1/finance/payments", json={
            "student_id": student_id,
            "amount": 600000.0,
            "payment_method": "CASH",
            "month_for": "2026-08",
            "note": "Avust oyi to'lovi"
        }, headers=admin_headers)
        assert p_res.status_code == 200

        # 2. Record Expense (150,000 UZS)
        e_res = await ac.post("/api/v1/finance/expenses", json={
            "title": "Internet va Kantselyariya",
            "amount": 150000.0,
            "category": "Kommunal va Ofis",
            "date": "2026-08-08"
        }, headers=admin_headers)
        assert e_res.status_code == 200

        # 3. Check Dashboard Stats (Net Profit = 600,000 - 150,000 = 450,000)
        stats_res = await ac.get("/api/v1/finance/dashboard-stats", headers=admin_headers)
        assert stats_res.status_code == 200
        s = stats_res.json()
        assert s["total_income"] == 600000.0
        assert s["total_expense"] == 150000.0
        assert s["net_profit"] == 450000.0

# ----------------------------------------------------
# 9. CRM LEADS TESTS
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_13_crm_leads_conversion():
    """13. CRM Lead yaratish va ENROLLED holatida avtomatik o'quvchiga aylantirish"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        admin_login = await ac.post("/api/v1/auth/login", json={"login_id": "777777", "password": "superadmin123"})
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

        # 1. Lead creation
        lead_res = await ac.post("/api/v1/crm/leads", json={
            "full_name": "Nigora Shokirova",
            "phone": "+998901119988",
            "notes": "Ingliz tili kursiga talabgor"
        })
        assert lead_res.status_code == 200
        lead_id = lead_res.json()["id"]

        # 2. Update status to ENROLLED
        conv_res = await ac.put(f"/api/v1/crm/leads/{lead_id}/status", json={"status": "ENROLLED"}, headers=admin_headers)
        assert conv_res.status_code == 200

        # 3. Check created student account
        st_res = await ac.get("/api/v1/users/?role=STUDENT", headers=admin_headers)
        names = [u["full_name"] for u in st_res.json()]
        assert "Nigora Shokirova" in names

# ----------------------------------------------------
# 10. CLICK MERCHANT WEBHOOK TESTS
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_14_click_merchant_webhook():
    """14. Click Merchant to'lov integratsiyasi (Prepare & Complete) testi"""
    import hashlib
    from app.core.config import settings
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        admin_login = await ac.post("/api/v1/auth/login", json={"login_id": "777777", "password": "superadmin123"})
        students = (await ac.get("/api/v1/users/?role=STUDENT", headers={"Authorization": f"Bearer {admin_login.json()['access_token']}"})).json()
        student_id = str(students[0]["id"])

        amount = 500000.0
        amount_str = f"{amount:.2f}".rstrip('0').rstrip('.')
        sign_time = "2026-08-08 20:00:00"

        # Prepare sign (action=0)
        src_0 = f"9998881112345{settings.CLICK_SECRET_KEY}{student_id}{amount_str}0{sign_time}"
        sign_0 = hashlib.md5(src_0.encode('utf-8')).hexdigest()

        # Prepare Action (action=0)
        prep_res = await ac.post("/api/v1/payments/click/webhook", data={
            "click_trans_id": "99988811",
            "service_id": "12345",
            "click_paydoc_id": "554433",
            "merchant_trans_id": student_id,
            "amount": amount,
            "action": 0,
            "error": 0,
            "sign_time": sign_time,
            "sign_string": sign_0
        })
        assert prep_res.status_code == 200
        assert prep_res.json()["error"] == 0

        # Complete sign (action=1)
        src_1 = f"9998881112345{settings.CLICK_SECRET_KEY}{student_id}{amount_str}1{sign_time}"
        sign_1 = hashlib.md5(src_1.encode('utf-8')).hexdigest()

        # Complete Action (action=1)
        comp_res = await ac.post("/api/v1/payments/click/webhook", data={
            "click_trans_id": "99988811",
            "service_id": "12345",
            "click_paydoc_id": "554433",
            "merchant_trans_id": student_id,
            "amount": amount,
            "action": 1,
            "error": 0,
            "sign_time": sign_time,
            "sign_string": sign_1
        })
        assert comp_res.status_code == 200
        assert comp_res.json()["error"] == 0
        assert "merchant_confirm_id" in comp_res.json()


# ----------------------------------------------------
# 11. TEACHER PAYROLL TESTS
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_15_teacher_payroll_calculation_and_payout():
    """15. O'qituvchilar maoshini foizda hisoblash va to'lash testi"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        admin_login = await ac.post("/api/v1/auth/login", json={"login_id": "777777", "password": "superadmin123"})
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

        teachers = (await ac.get("/api/v1/users/?role=TEACHER", headers=admin_headers)).json()
        teacher_id = teachers[0]["id"]

        # Calculate Payroll for 2026-08 (40% rate)
        calc_res = await ac.post("/api/v1/finance/payroll/calculate", json={
            "teacher_id": teacher_id,
            "month_for": "2026-08",
            "percentage_rate": 40.0
        }, headers=admin_headers)
        assert calc_res.status_code == 200
        payroll_id = calc_res.json()["id"]

        # Pay Salary out
        pay_res = await ac.post("/api/v1/finance/payroll/pay", json={
            "payroll_id": payroll_id,
            "amount": 240000.0,
            "note": "Avqust oyi 1-qism maoshi"
        }, headers=admin_headers)
        assert pay_res.status_code == 200

# ----------------------------------------------------
# 12. MONTHLY BILLING & DEBTORS TESTS
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_16_monthly_billing_and_debtors_list():
    """16. Oylik billing shakllantirish va qarzdorlar ro'yxatini olish testi"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        admin_login = await ac.post("/api/v1/auth/login", json={"login_id": "777777", "password": "superadmin123"})
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

        # Generate Billing for 2026-08
        gen_res = await ac.post("/api/v1/finance/billing/generate", json={
            "month_for": "2026-08",
            "due_date": "2026-08-10"
        }, headers=admin_headers)
        assert gen_res.status_code == 200

        # List Debtors
        debtors_res = await ac.get("/api/v1/finance/debtors", headers=admin_headers)
        assert debtors_res.status_code == 200
        assert isinstance(debtors_res.json(), list)

# ----------------------------------------------------
# 13. EXAMS & RESULTS TESTS
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_17_exams_creation_and_grading():
    """17. Imtihon yaratish va natijalarni kiritish testi"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        admin_login = await ac.post("/api/v1/auth/login", json={"login_id": "777777", "password": "superadmin123"})
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

        courses = (await ac.get("/api/v1/courses/", headers=admin_headers)).json()
        rooms = (await ac.get("/api/v1/courses/rooms", headers=admin_headers)).json()
        teachers = (await ac.get("/api/v1/users/?role=TEACHER", headers=admin_headers)).json()
        students = (await ac.get("/api/v1/users/?role=STUDENT", headers=admin_headers)).json()

        g_res = await ac.post("/api/v1/groups/", json={
            "name": "IELTS Mock Group",
            "course_id": courses[0]["id"],
            "teacher_id": teachers[0]["id"],
            "room_id": rooms[0]["id"],
            "days_of_week": "MON,WED",
            "start_time": "08:00",
            "end_time": "10:00"
        }, headers=admin_headers)
        group_id = g_res.json()["id"]

        # Teacher Login
        t_login = await ac.post("/api/v1/auth/login", json={"login_id": "200201", "password": "teacher123"})
        t_headers = {"Authorization": f"Bearer {t_login.json()['access_token']}"}

        # Teacher creates Exam
        exam_res = await ac.post("/api/v1/analytics/exams", json={
            "group_id": group_id,
            "title": "Monthly IELTS Mock Exam #1",
            "max_score": 9.0,
            "exam_date": "2026-08-08"
        }, headers=t_headers)
        assert exam_res.status_code == 200
        exam_id = exam_res.json()["id"]

        # Record Exam Results
        res_res = await ac.post("/api/v1/analytics/exams/results", json={
            "exam_id": exam_id,
            "results": [
                {
                    "student_id": students[0]["id"],
                    "score": 7.5,
                    "feedback": "Overall Band 7.5 - Excellent Reading & Listening"
                }
            ]
        }, headers=t_headers)
        assert res_res.status_code == 200

# ----------------------------------------------------
# 14. LEADERBOARD & STUDENT ANALYTICS TESTS
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_18_leaderboard_and_student_analytics():
    """18. Top o'quvchilar reytingi (Leaderboard) va O'quvchi shaxsiy analitikasi testi"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        admin_login = await ac.post("/api/v1/auth/login", json={"login_id": "777777", "password": "superadmin123"})
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

        students = (await ac.get("/api/v1/users/?role=STUDENT", headers=admin_headers)).json()
        student_id = students[0]["id"]

        # Get Leaderboard
        lb_res = await ac.get("/api/v1/analytics/leaderboard?limit=5", headers=admin_headers)
        assert lb_res.status_code == 200
        assert len(lb_res.json()) >= 1
        assert lb_res.json()[0]["rank"] == 1

        # Get Student Analytics
        an_res = await ac.get(f"/api/v1/analytics/student/{student_id}", headers=admin_headers)
        assert an_res.status_code == 200
        data = an_res.json()
        assert "attendance_rate_percentage" in data
        assert "average_exam_score" in data

# ----------------------------------------------------
# 15. SECURITY HARDENING CHECKS
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_19_security_hardening_checks():
    """19. HTTP Security Headers, Taqiqlangan fayl yuklashni bloklash va Click MD5 Sign xavfsizlik sinovi"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Security Headers Verification
        root_res = await ac.get("/")
        assert root_res.headers.get("X-Frame-Options") == "DENY"
        assert root_res.headers.get("X-Content-Type-Options") == "nosniff"

        # 2. Prohibited File Upload Prevention (e.g. .exe file)
        s_login = await ac.post("/api/v1/auth/login", json={"login_id": "100101", "password": "Ali"})
        s_headers = {"Authorization": f"Bearer {s_login.json()['access_token']}"}

        files = {"file": ("script.exe", b"binary content", "application/octet-stream")}
        bad_upload_res = await ac.post("/api/v1/homework/submit", data={"homework_id": 1, "text_submission": "test"}, files=files, headers=s_headers)
        assert bad_upload_res.status_code == 400
        detail_text = bad_upload_res.json()["detail"]
        assert "Xavfsizlik" in detail_text or "taqiqlangan" in detail_text.lower()

        # 3. Tampered Click MD5 Signature Rejection
        click_res = await ac.post("/api/v1/payments/click/webhook", data={
            "click_trans_id": "123",
            "service_id": "12345",
            "click_paydoc_id": "123",
            "merchant_trans_id": "1",
            "amount": 1000.0,
            "action": 1,
            "error": 0,
            "sign_time": "2026-08-08 20:00:00",
            "sign_string": "invalid_md5_hash_sample"
        })
        assert click_res.status_code == 200
        assert click_res.json()["error"] == -8

# ----------------------------------------------------
# 16. EXAM TEST BANK & ONLINE/OFFLINE EXAMS & CERTIFICATES TESTS
# ----------------------------------------------------
@pytest.mark.asyncio
async def test_20_questions_bank_and_format_parser():
    """20. Savollar bankiga (?, +, -) formati orqali matndan savollar import qilish va qo'lda savol yaratish testi"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        t_login = await ac.post("/api/v1/auth/login", json={"login_id": "200201", "password": "teacher123"})
        t_headers = {"Authorization": f"Bearer {t_login.json()['access_token']}"}

        # 1. Manual question create
        q_res = await ac.post("/api/v1/analytics/questions", json={
            "question_text": "Python qanday dasturlash tili?",
            "correct_answer": "Yuqori darajali interpretatsiya qilinuvchi til",
            "options": [
                "Yuqori darajali interpretatsiya qilinuvchi til",
                "Quyi darajali assembler tili",
                "Faqat brauzerda ishlaydigan til",
                "Dasturlash tili emas"
            ]
        }, headers=t_headers)
        assert q_res.status_code == 200
        assert q_res.json()["correct_answer"] == "Yuqori darajali interpretatsiya qilinuvchi til"

        # 2. Text import with ?, +, - format
        raw_text_sample = """
        ? O'zbekiston poytaxti qaysi shahar?
        + Toshkent
        - Samarqand
        - Buxoro
        - Andijon

        ? 15 * 4 nechiga teng?
        - 50
        + 60
        - 70
        - 80
        """
        import_res = await ac.post("/api/v1/analytics/questions/import-text", json={
            "raw_text": raw_text_sample
        }, headers=t_headers)
        assert import_res.status_code == 200
        assert import_res.json()["count"] == 2

        # 3. List questions
        list_res = await ac.get("/api/v1/analytics/questions", headers=t_headers)
        assert list_res.status_code == 200
        assert len(list_res.json()) >= 3


@pytest.mark.asyncio
async def test_21_online_exam_flow_and_auto_certificate():
    """21. Online imtihon yaratish, boshlash (taymer), o'quvchi tomonidan topshirish va avtomatik sertifikat yaratish testi"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        admin_login = await ac.post("/api/v1/auth/login", json={"login_id": "777777", "password": "superadmin123"})
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

        # Create Course & Group
        course_res = await ac.post("/api/v1/courses/", json={
            "title": "Fullstack Web Development",
            "price_monthly": 700000.0,
            "duration_months": 6
        }, headers=admin_headers)
        course_id = course_res.json()["id"]

        room_res = await ac.get("/api/v1/courses/rooms", headers=admin_headers)
        room_id = room_res.json()[0]["id"]
        teachers = (await ac.get("/api/v1/users/?role=TEACHER", headers=admin_headers)).json()
        students = (await ac.get("/api/v1/users/?role=STUDENT", headers=admin_headers)).json()

        group_res = await ac.post("/api/v1/groups/", json={
            "name": "Web-101 Group",
            "course_id": course_id,
            "teacher_id": teachers[0]["id"],
            "room_id": room_id,
            "days_of_week": "Dush-Chor-Jum",
            "start_time": "14:00",
            "end_time": "16:00"
        }, headers=admin_headers)
        group_id = group_res.json()["id"]

        # Add student to group
        await ac.post(f"/api/v1/groups/{group_id}/students/{students[0]['id']}", headers=admin_headers)

        # Teacher login
        t_login = await ac.post("/api/v1/auth/login", json={"login_id": "200201", "password": "teacher123"})
        t_headers = {"Authorization": f"Bearer {t_login.json()['access_token']}"}

        # Create Online Exam with selected questions
        import json
        questions_payload = json.dumps([
            {
                "question_text": "React nima?",
                "options": ["Frontend kutubxona", "Ma'lumotlar bazasi", "Operatsion tizim", "Protsessor"],
                "correct_answer": "Frontend kutubxona"
            },
            {
                "question_text": "HTML kengaytmasi nima?",
                "options": ["Hyper Text Markup Language", "High Tech Multi Language", "Home Tool Markup", "None"],
                "correct_answer": "Hyper Text Markup Language"
            }
        ])

        exam_res = await ac.post("/api/v1/analytics/exams", json={
            "group_id": group_id,
            "title": "Web Development Midterm Exam",
            "exam_type": "ONLINE",
            "max_score": 100.0,
            "pass_score": 70.0,
            "duration_minutes": 20,
            "questions_data": questions_payload,
            "exam_date": "2026-08-18"
        }, headers=t_headers)
        assert exam_res.status_code == 200
        exam_id = exam_res.json()["id"]

        # Teacher starts exam (Status -> ACTIVE)
        start_res = await ac.post(f"/api/v1/analytics/exams/{exam_id}/start", headers=t_headers)
        assert start_res.status_code == 200
        assert start_res.json()["status"] == "ACTIVE"

        # Student login (Ali Valiyev)
        s_login = await ac.post("/api/v1/auth/login", json={"login_id": "100101", "password": "Ali"})
        s_headers = {"Authorization": f"Bearer {s_login.json()['access_token']}"}

        # Student checks their exams
        my_exams_res = await ac.get("/api/v1/analytics/exams/student/my", headers=s_headers)
        assert my_exams_res.status_code == 200
        assert len(my_exams_res.json()) >= 1
        assert my_exams_res.json()[0]["status"] == "ACTIVE"

        # Student submits online exam with 100% correct answers
        submit_res = await ac.post(f"/api/v1/analytics/exams/{exam_id}/submit", json={
            "answers": {
                "0": "Frontend kutubxona",
                "1": "Hyper Text Markup Language"
            }
        }, headers=s_headers)
        assert submit_res.status_code == 200
        sub_data = submit_res.json()
        assert sub_data["score"] == 100.0
        assert sub_data["is_passed"] is True
        assert sub_data["certificate_awarded"] is True
        assert sub_data["certificate_code"] is not None

        # Student checks their certificates
        my_certs_res = await ac.get("/api/v1/certificates/my", headers=s_headers)
        assert my_certs_res.status_code == 200
        assert len(my_certs_res.json()) >= 1
        cert_code = my_certs_res.json()[0]["certificate_code"]

        # Verify Certificate
        verify_res = await ac.get(f"/api/v1/certificates/verify/{cert_code}")
        assert verify_res.status_code == 200
        assert verify_res.json()["student_name"] == "Ali Valiyev"


@pytest.mark.asyncio
async def test_22_offline_exam_results_and_certificate():
    """22. Offline imtihon o'tkazish, o'qituvchi tomonidan ball kiritish va o'tish balidan yuqoriga sertifikat berish testi"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        admin_login = await ac.post("/api/v1/auth/login", json={"login_id": "777777", "password": "superadmin123"})
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

        # Create Course & Group
        course_res = await ac.post("/api/v1/courses/", json={
            "title": "General English B2",
            "price_monthly": 550000.0,
            "duration_months": 3
        }, headers=admin_headers)
        course_id = course_res.json()["id"]

        room_res = await ac.get("/api/v1/courses/rooms", headers=admin_headers)
        room_id = room_res.json()[0]["id"]
        teachers = (await ac.get("/api/v1/users/?role=TEACHER", headers=admin_headers)).json()
        students = (await ac.get("/api/v1/users/?role=STUDENT", headers=admin_headers)).json()

        group_res = await ac.post("/api/v1/groups/", json={
            "name": "English-B2 Group",
            "course_id": course_id,
            "teacher_id": teachers[0]["id"],
            "room_id": room_id,
            "days_of_week": "Sesh-Pay-Shan",
            "start_time": "16:00",
            "end_time": "18:00"
        }, headers=admin_headers)
        group_id = group_res.json()["id"]

        # Add student
        await ac.post(f"/api/v1/groups/{group_id}/students/{students[0]['id']}", headers=admin_headers)

        # Teacher login
        t_login = await ac.post("/api/v1/auth/login", json={"login_id": "200201", "password": "teacher123"})
        t_headers = {"Authorization": f"Bearer {t_login.json()['access_token']}"}

        # Create Offline Exam
        exam_res = await ac.post("/api/v1/analytics/exams", json={
            "group_id": group_id,
            "title": "English B2 Final Written Exam",
            "exam_type": "OFFLINE",
            "max_score": 100.0,
            "pass_score": 80.0,
            "duration_minutes": 60,
            "exam_date": "2026-08-18"
        }, headers=t_headers)
        assert exam_res.status_code == 200
        exam_id = exam_res.json()["id"]

        # Teacher records offline scores (score: 92 > pass_score 80)
        res_save = await ac.post("/api/v1/analytics/exams/results", json={
            "exam_id": exam_id,
            "results": [
                {
                    "student_id": students[0]["id"],
                    "score": 92.0,
                    "feedback": "A'lo darajada yozma imtihon topshirdi"
                }
            ]
        }, headers=t_headers)
        assert res_save.status_code == 200
        assert res_save.json()["certificates_awarded"] == 1

        # Check Exam Results detailed endpoint
        exam_results_res = await ac.get(f"/api/v1/analytics/exams/{exam_id}/results", headers=t_headers)
        assert exam_results_res.status_code == 200
        assert len(exam_results_res.json()) == 1
        assert exam_results_res.json()[0]["is_passed"] is True
        assert exam_results_res.json()[0]["certificate_code"] is not None

@pytest.mark.asyncio
async def test_23_manual_room_creation_and_admin_attendance():
    """23. Guruh qo'shishda xonani qo'lda (room_name) kiritish va admin davomat monitoringi testi"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        admin_login = await ac.post("/api/v1/auth/login", json={"login_id": "777777", "password": "superadmin123"})
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

        # 1. Guruhni qo'lda kiritilgan xona nomi bilan yaratish
        grp_res = await ac.post("/api/v1/groups/", json={
            "name": "Robotics Master 01",
            "course_id": 1,
            "teacher_id": 4,
            "room_name": "304-Robototexnika Laboratoriyasi",
            "days_of_week": "TUE,THU,SAT",
            "start_time": "16:00",
            "end_time": "18:00"
        }, headers=admin_headers)
        assert grp_res.status_code == 200
        group_data = grp_res.json()
        assert group_data["name"] == "Robotics Master 01"
        assert group_data["room_id"] is not None

        # 2. Xona haqiqatan yaratilganligini tekshirish
        rooms_res = await ac.get("/api/v1/courses/rooms", headers=admin_headers)
        assert rooms_res.status_code == 200
        room_names = [r["name"] for r in rooms_res.json()]
        assert "304-Robototexnika Laboratoriyasi" in room_names

        # 3. Admin davomat monitoringi endpointi testi
        att_res = await ac.get("/api/v1/attendance/all", headers=admin_headers)
        assert att_res.status_code == 200
        assert isinstance(att_res.json(), list)

@pytest.mark.asyncio
async def test_24_payment_edit_delete_and_billing_recalc():
    """24. To'lovni yaratish, tahrirlash, o'chirish va billing hisob-kitobining qayta sinxronizatsiyasi testi"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        admin_login = await ac.post("/api/v1/auth/login", json={"login_id": "777777", "password": "superadmin123"})
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

        students = (await ac.get("/api/v1/users/?role=STUDENT", headers=admin_headers)).json()
        student_id = students[0]["id"]
        test_month = "2026-09"

        # 1. 300,000 so'm to'lov qabul qilish
        pay_res = await ac.post("/api/v1/finance/payments", json={
            "student_id": student_id,
            "amount": 300000.0,
            "payment_method": "CASH",
            "month_for": test_month,
            "note": "Sentyabr oyi boshlang'ich to'lovi"
        }, headers=admin_headers)
        assert pay_res.status_code == 200
        payment_id = pay_res.json()["payment_id"]

        # 2. Billing ma'lumotlarini tekshirish (month_amount_paid 300,000 bo'lishi kerak)
        info_res = await ac.get(f"/api/v1/finance/student/{student_id}/billing-info?month_for={test_month}", headers=admin_headers)
        assert info_res.status_code == 200
        info = info_res.json()
        assert info["month_amount_paid"] == 300000.0
        assert info["month_remaining_due"] == max(0.0, info["month_amount_due"] - 300000.0)

        # 3. To'lovni tahrirlash: summani 450,000 so'mga o'zgartirish
        update_res = await ac.put(f"/api/v1/finance/payments/{payment_id}", json={
            "amount": 450000.0,
            "note": "Tahrirlangan to'lov 450 ming"
        }, headers=admin_headers)
        assert update_res.status_code == 200
        assert update_res.json()["amount"] == 450000.0

        # 4. Tahrirdan so'ng billing ma'lumotlarini tekshirish
        info_res2 = await ac.get(f"/api/v1/finance/student/{student_id}/billing-info?month_for={test_month}", headers=admin_headers)
        assert info_res2.status_code == 200
        info2 = info_res2.json()
        assert info2["month_amount_paid"] == 450000.0
        assert info2["month_remaining_due"] == max(0.0, info2["month_amount_due"] - 450000.0)

        # 5. To'lovni o'chirish
        del_res = await ac.delete(f"/api/v1/finance/payments/{payment_id}", headers=admin_headers)
        assert del_res.status_code == 200
        assert del_res.json()["payment_id"] == payment_id

        # 6. O'chirilgandan so'ng billing ma'lumotlarini tekshirish (month_amount_paid 0 bo'lishi kerak)
        info_res3 = await ac.get(f"/api/v1/finance/student/{student_id}/billing-info?month_for={test_month}", headers=admin_headers)
        assert info_res3.status_code == 200
        info3 = info_res3.json()
        assert info3["month_amount_paid"] == 0.0

@pytest.mark.asyncio
async def test_25_admin_groups_attendance_summary_and_journal_matrix():
    """25. Guruhlar davomat statistikasi (summary) va guruh jurnali (matrix) testi"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        admin_login = await ac.post("/api/v1/auth/login", json={"login_id": "777777", "password": "superadmin123"})
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

        # 1. Sinov guruhi yaratish
        grp_res = await ac.post("/api/v1/groups/", json={
            "name": "FullStack Attendance Test Group",
            "course_id": 1,
            "teacher_id": 4,
            "room_name": "101-Davomat Xonasi",
            "days_of_week": "MON,WED,FRI",
            "start_time": "14:00",
            "end_time": "16:00"
        }, headers=admin_headers)
        assert grp_res.status_code == 200
        group_id = grp_res.json()["id"]

        # 2. O'quvchini guruhga biriktirish
        students = (await ac.get("/api/v1/users/?role=STUDENT", headers=admin_headers)).json()
        student_id = students[0]["id"]
        await ac.post(f"/api/v1/groups/{group_id}/students/{student_id}", headers=admin_headers)

        # 3. Guruhlar davomat xulosasini olish (nechtadan nechta kelgani)
        summary_res = await ac.get("/api/v1/attendance/groups-summary", headers=admin_headers)
        assert summary_res.status_code == 200
        summaries = summary_res.json()
        assert isinstance(summaries, list)
        matching_grp = next((g for g in summaries if g["group_id"] == group_id), None)
        assert matching_grp is not None
        assert matching_grp["total_students"] == 1

        # 4. Yangi dars sanasini yaratish
        lesson_res = await ac.post("/api/v1/attendance/lessons", json={
            "group_id": group_id,
            "lesson_date": "2026-08-25",
            "topic": "Test Dars Mavzusi"
        }, headers=admin_headers)
        assert lesson_res.status_code == 200
        lesson_id = lesson_res.json()["id"]

        # 5. Davomat qilish (Keldi ✅)
        mark_res = await ac.post("/api/v1/attendance/mark", json={
            "lesson_id": lesson_id,
            "attendances": [
                {"student_id": student_id, "status": "PRESENT", "note": "Vaqtida keldi"}
            ]
        }, headers=admin_headers)
        assert mark_res.status_code == 200

        # 6. Guruh davomat jurnali (matrix) endpointini tekshirish
        journal_res = await ac.get(f"/api/v1/attendance/group/{group_id}/journal", headers=admin_headers)
        assert journal_res.status_code == 200
        journal = journal_res.json()
        assert "group" in journal
        assert "students" in journal
        assert "lessons" in journal
        assert "matrix" in journal
        assert len(journal["students"]) == 1
        assert len(journal["lessons"]) == 1
        assert journal["matrix"][str(student_id)][str(lesson_id)]["status"] == "PRESENT"

@pytest.mark.asyncio
async def test_26_teacher_group_students_billing_and_debt_tracking():
    """26. O'qituvchi panelida o'quvchilar qarzdorligi va to'lovlarini to'g'ri ko'rsatish testi"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        admin_login = await ac.post("/api/v1/auth/login", json={"login_id": "777777", "password": "superadmin123"})
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

        teacher_login = await ac.post("/api/v1/auth/login", json={"login_id": "200201", "password": "teacher123"})
        teacher_headers = {"Authorization": f"Bearer {teacher_login.json()['access_token']}"}

        # 1. Guruh yaratish va o'quvchini biriktirish
        grp_res = await ac.post("/api/v1/groups/", json={
            "name": "Teacher Billing Test Group",
            "course_id": 1,
            "teacher_id": 4,
            "room_name": "202-Xona",
            "days_of_week": "TUE,THU,SAT",
            "start_time": "10:00",
            "end_time": "12:00"
        }, headers=admin_headers)
        assert grp_res.status_code == 200
        group_id = grp_res.json()["id"]

        students = (await ac.get("/api/v1/users/?role=STUDENT", headers=admin_headers)).json()
        student_id = students[0]["id"]
        await ac.post(f"/api/v1/groups/{group_id}/students/{student_id}", headers=admin_headers)

        test_month = "2026-08"

        # 2. To'lov qilinmagan holatda o'qituvchi guruh billingini so'raydi
        unpaid_res = await ac.get(f"/api/v1/finance/group/{group_id}/students-billing?month_for={test_month}", headers=teacher_headers)
        assert unpaid_res.status_code == 200
        unpaid_list = unpaid_res.json()
        assert len(unpaid_list) == 1
        assert unpaid_list[0]["student_id"] == student_id
        assert unpaid_list[0]["amount_paid"] == 0.0
        assert unpaid_list[0]["remaining_due"] == 600000.0
        assert unpaid_list[0]["is_paid"] is False
        assert unpaid_list[0]["status"] == "UNPAID"

        # 3. O'quvchi qisman 250,000 to'lov qilganda
        await ac.post("/api/v1/finance/payments", json={
            "student_id": student_id,
            "amount": 250000.0,
            "payment_method": "CLICK",
            "month_for": test_month,
            "note": "Qisman to'lov"
        }, headers=admin_headers)

        partial_res = await ac.get(f"/api/v1/finance/group/{group_id}/students-billing?month_for={test_month}", headers=teacher_headers)
        assert partial_res.status_code == 200
        partial_list = partial_res.json()
        assert partial_list[0]["amount_paid"] == 250000.0
        assert partial_list[0]["remaining_due"] == 350000.0
        assert partial_list[0]["is_partial"] is True
        assert partial_list[0]["status"] == "PARTIAL"

        # 4. Qolgan 350,000 to'langanda to'liq "PAID" bo'lishi
        await ac.post("/api/v1/finance/payments", json={
            "student_id": student_id,
            "amount": 350000.0,
            "payment_method": "CASH",
            "month_for": test_month,
            "note": "To'liq yopish"
        }, headers=admin_headers)

        paid_res = await ac.get(f"/api/v1/finance/group/{group_id}/students-billing?month_for={test_month}", headers=teacher_headers)
        assert paid_res.status_code == 200
        paid_list = paid_res.json()
        assert paid_list[0]["amount_paid"] == 600000.0
        assert paid_list[0]["remaining_due"] == 0.0
        assert paid_list[0]["is_paid"] is True
        assert paid_list[0]["status"] == "PAID"


@pytest.mark.asyncio
async def test_27_teacher_group_journal_and_homework_submissions():
    """27. O'qituvchi guruh jurnali (matrix) va uy vazifalari topshirig'i testi"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        admin_login = await ac.post("/api/v1/auth/login", json={"login_id": "777777", "password": "superadmin123"})
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

        # 1. Guruh va o'qituvchini olish
        t_login = await ac.post("/api/v1/auth/login", json={"login_id": "200201", "password": "teacher123"})
        teacher_headers = {"Authorization": f"Bearer {t_login.json()['access_token']}"}

        grp_res = await ac.post("/api/v1/groups/", json={
            "name": "Teacher Journal Test Group",
            "course_id": 1,
            "teacher_id": 4,
            "room_name": "203-Xona",
            "days_of_week": "MON,WED,FRI",
            "start_time": "14:00",
            "end_time": "16:00"
        }, headers=admin_headers)
        assert grp_res.status_code == 200
        group_id = grp_res.json()["id"]

        # 2. O'qituvchi guruh davomat jurnalini so'raydi (Matrix)
        journal_res = await ac.get(f"/api/v1/attendance/group/{group_id}/journal", headers=teacher_headers)
        assert journal_res.status_code == 200
        j_data = journal_res.json()
        assert "group" in j_data
        assert "students" in j_data
        assert "lessons" in j_data
        assert "matrix" in j_data

        # 3. O'qituvchi guruhga yangi uy vazifasi yaratadi
        hw_res = await ac.post("/api/v1/homework/", data={
            "group_id": group_id,
            "title": "Unit 7 Homework",
            "description": "Sahifa 45-dagi barcha mashqlar",
            "max_coins": 15
        }, headers=teacher_headers)
        assert hw_res.status_code == 200
        hw_id = hw_res.json()["id"]

        # 4. Guruh vazifalari ro'yxatini tekshirish
        list_hws = await ac.get(f"/api/v1/homework/group/{group_id}", headers=teacher_headers)
        assert list_hws.status_code == 200
        assert any(h["id"] == hw_id for h in list_hws.json())

        # 5. Topshirilgan ishlar ro'yxatini so'rash
        subs_res = await ac.get(f"/api/v1/homework/{hw_id}/submissions", headers=teacher_headers)
        assert subs_res.status_code == 200
        assert isinstance(subs_res.json(), list)

@pytest.mark.asyncio
async def test_28_student_without_phone_and_parents_phones():
    """28. Telefon raqamisiz o'quvchi qo'shish, otasi va onasi raqamlarini saqlash testi"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        admin_login = await ac.post("/api/v1/auth/login", json={"login_id": "777777", "password": "superadmin123"})
        admin_token = admin_login.json()["access_token"]
        headers = {"Authorization": f"Bearer {admin_token}"}

        # 1. Shaxsiy telefonisiz, faqat otasi va onasi raqami bilan o'quvchi yaratish
        create_res = await ac.post("/api/v1/users/", json={
            "full_name": "Jasur Bekov",
            "phone": None,
            "father_phone": "+998901112233",
            "mother_phone": "+998904445566",
            "role": "STUDENT"
        }, headers=headers)
        assert create_res.status_code == 200
        st_data = create_res.json()
        assert st_data["full_name"] == "Jasur Bekov"
        assert st_data["phone"] is None
        assert st_data["father_phone"] == "+998901112233"
        assert st_data["mother_phone"] == "+998904445566"
        assert st_data["parent_phone"] == "+998901112233" # fallback
        assert "login_id" in st_data
        st_id = st_data["id"]

        # 2. O'quvchini tahrirlash (onasining raqamini yangilash)
        update_res = await ac.put(f"/api/v1/users/{st_id}", json={
            "mother_phone": "+998909990011"
        }, headers=headers)
        assert update_res.status_code == 200
        assert update_res.json()["mother_phone"] == "+998909990011"

        # 3. Lead yaratish (shaxsiy telefonisiz, ota-ona nomeri bilan) va uni ENROLLED qilish
        lead_res = await ac.post("/api/v1/crm/leads", json={
            "full_name": "Sardor Aliyev",
            "phone": None,
            "father_phone": "+998912223344",
            "mother_phone": "+998915556677",
            "notes": "Yangi kelgan o'quvchi arizasi"
        })
        assert lead_res.status_code == 200
        lead_id = lead_res.json()["id"]

        # 4. Lead holatini ENROLLED qilish va yangi o'quvchi avtomatik yaratilishini tekshirish
        enroll_res = await ac.put(f"/api/v1/crm/leads/{lead_id}/status", json={
            "status": "ENROLLED",
            "notes": "Qabul qilindi va guruhga qo'shildi"
        }, headers=headers)
        assert enroll_res.status_code == 200
        assert "new_login_id" in enroll_res.json()
        new_login = enroll_res.json()["new_login_id"]

        # Yaratilgan o'quvchini tekshirish
        users_list = await ac.get("/api/v1/users/", headers=headers)
        created_student = next((u for u in users_list.json() if u["login_id"] == new_login), None)
        assert created_student is not None
        assert created_student["full_name"] == "Sardor Aliyev"
        assert created_student["father_phone"] == "+998912223344"
        assert created_student["mother_phone"] == "+998915556677"









