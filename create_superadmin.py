import asyncio
import os
from sqlalchemy import select
from app.core.database import AsyncSessionLocal, engine, Base
from app.core.security import get_password_hash
from app.models.models import User, UserRole

async def create_superadmin():
    admin_login = os.getenv('ADMIN_LOGIN_ID', '777777')
    admin_phone = os.getenv('ADMIN_PHONE', '+998907777777')
    admin_password = os.getenv('ADMIN_PASSWORD')

    if not admin_password:
        print("XATOLIK: ADMIN_PASSWORD environment variable o'rnatilmagan!")
        print("Ishga tushirish: ADMIN_PASSWORD=YourSecurePassword python create_superadmin.py")
        return

    # Database jadvallarini yaratish
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        stmt = select(User).where(User.login_id == admin_login)
        res = await session.execute(stmt)
        super_admin = res.scalar_one_or_none()

        if not super_admin:
            super_admin = User(
                login_id=admin_login,
                full_name="Super Admin",
                phone=admin_phone,
                hashed_password=get_password_hash(admin_password),
                is_password_changed=True,
                role=UserRole.ADMIN
            )
            session.add(super_admin)
            await session.commit()
            print(f"SUCCESS: Super Admin yaratildi! Login ID: {admin_login}")
        else:
            print(f"INFO: Super Admin ({admin_login}) allaqachon mavjud.")

if __name__ == "__main__":
    asyncio.run(create_superadmin())
