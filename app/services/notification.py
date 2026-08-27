import logging
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)

async def send_telegram_notification(chat_id: str, text: str):
    if not settings.TELEGRAM_BOT_TOKEN or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, timeout=5.0)
            if response.status_code != 200:
                logger.warning(f"Telegram bildirishnoma yuborishda xatolik: chat_id={chat_id}, status={response.status_code}")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Telegram API ga ulanishda xatolik: {e}")
            return False
