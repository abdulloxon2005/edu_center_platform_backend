import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date
import os
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.core.config import settings
from app.core.database import engine, Base, AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.models import User, UserRole, Room
from app.api.v1.router import api_router

# Logging konfiguratsiyasi
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

async def monthly_billing_scheduler():
    """Har 30 minutda tekshirib, yangi oyning 1-sanasida avtomatik to'lov billingini shakllantiruvchi foniy vazifa"""
    last_processed_month = None
    while True:
        try:
            today = date.today()
            current_month = today.strftime("%Y-%m")
            if today.day == 1 and last_processed_month != current_month:
                logger.info(f"Oylik avtomatik billing boshlanmoqda: {current_month}")
                from app.api.v1.finance import execute_monthly_billing_and_notify
                async with AsyncSessionLocal() as session:
                    res = await execute_monthly_billing_and_notify(session, current_month)
                    logger.info(f"Oylik billing natijasi: {res}")
                last_processed_month = current_month
        except Exception as e:
            logger.error(f"Oylik billing scheduler xatosi: {e}")
        await asyncio.sleep(1800)

from app.core.db_migrate import ensure_sqlite_columns

@asynccontextmanager
async def lifespan(app: FastAPI):
    # App ishga tushganda SQLite jadvallarini avtomatik yaratish va yangilash
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    ensure_sqlite_columns()
    
    # Boshlang'ich Super Admin (faqat development muhitda)
    if settings.ENVIRONMENT == 'development':
        async with AsyncSessionLocal() as session:
            # Super Admin (Login ID: 777777)
            super_res = await session.execute(select(User).where(User.login_id == "777777"))
            if not super_res.scalar_one_or_none():
                admin_password = os.environ.get("ADMIN_PASSWORD", "Admin2026!x")
                super_admin = User(
                    login_id="777777",
                    full_name="Super Admin",
                    phone="+998907777777",
                    hashed_password=get_password_hash(admin_password),
                    is_password_changed=True,
                    role=UserRole.ADMIN
                )
                session.add(super_admin)
                logger.info("Development: Super Admin yaratildi (Login: 777777)")
    
            # Dars xonasi
            room_res = await session.execute(select(Room))
            if not room_res.scalars().first():
                room1 = Room(name="1-xona (Kompyuter sinfi)", capacity=20, description="Asosiy dars xonasi")
                session.add(room1)
    
            await session.commit()
    
    # Oylik avtomatik billing foniy vazifasi
    cron_task = asyncio.create_task(monthly_billing_scheduler())
    
    yield

    cron_task.cancel()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# HTTP Xavfsizlik Sarlavhalari (Security Headers) Middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.all_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["*"],
)


os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/")
async def root():
    return {
        "message": "Ta'lim Plus O'quv Markazi FastAPI Server ishlamoqda! 🚀",
        "docs": "/docs",
        "status": "active"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
