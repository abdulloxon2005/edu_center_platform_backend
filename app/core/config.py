import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "O'quv Markazi Boshqaruv Tizimi API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"  # 'development' or 'production'
    
    # Xavfsizlik: .env faylda o'rnatilishi SHART
    SECRET_KEY: str = "CHANGE_ME_IN_ENV_FILE"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30  # 30 minut
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7     # 7 kun

    # Baza konfiguratsiyasi
    DATABASE_URL: str = "sqlite+aiosqlite:///./oquv_markaz.db"
    
    # Telegram Bot
    TELEGRAM_BOT_TOKEN: str = ""
    
    # Click Merchant API Security
    CLICK_SECRET_KEY: str = "CHANGE_ME_IN_ENV_FILE"
    CLICK_SERVICE_ID: str = "CHANGE_ME_IN_ENV_FILE"
    
    # CORS Ruxsat berilgan domenlar
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:5173", "http://localhost:5174", "http://localhost:5175",
        "http://localhost:5176", "http://localhost:5177", "http://localhost:5178",
        "http://localhost:5179", "http://localhost:5180",
        "http://localhost:3000", "http://127.0.0.1:5173"
    ]
    EXTRA_CORS_ORIGINS: str = ""  # Comma-separated production domains

    # Fayl saqlash xavfsizligi
    ALLOWED_UPLOAD_EXTENSIONS: List[str] = [".pdf", ".png", ".jpg", ".jpeg", ".docx", ".zip", ".rar", ".txt"]
    MAX_UPLOAD_SIZE_MB: int = 15

    # Parol kuchliligi
    MIN_PASSWORD_LENGTH: int = 8

    # Fayl saqlash
    UPLOAD_DIR: str = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def all_cors_origins(self) -> List[str]:
        origins = self.ALLOWED_ORIGINS.copy()
        if self.EXTRA_CORS_ORIGINS:
            origins.extend([o.strip() for o in self.EXTRA_CORS_ORIGINS.split(",") if o.strip()])
        return origins


settings = Settings()
