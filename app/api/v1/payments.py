import hashlib
import logging
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.config import settings
from app.models.models import Payment, PaymentMethod, User

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/click/webhook")
async def click_webhook(
    click_trans_id: str = Form(...),
    service_id: str = Form(...),
    click_paydoc_id: str = Form(...),
    merchant_trans_id: str = Form(...),
    amount: float = Form(...),
    action: int = Form(...),
    error: int = Form(...),
    error_note: str = Form(""),
    sign_time: str = Form(...),
    sign_string: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    if error < 0:
        return {"error": -1, "error_note": "Transaction error"}

    # Click Signature Verification (DUMMY bypass OLIB TASHLANDI)
    amount_str = f"{amount:.2f}".rstrip('0').rstrip('.')
    sign_source = f"{click_trans_id}{service_id}{settings.CLICK_SECRET_KEY}{merchant_trans_id}{amount_str}{action}{sign_time}"
    expected_sign = hashlib.md5(sign_source.encode('utf-8')).hexdigest()
    
    if sign_string.lower() != expected_sign.lower():
        logger.warning(f"Click webhook: noto'g'ri imzo. trans_id={click_trans_id}")
        return {"error": -8, "error_note": "Error in sign"}

    student_id = int(merchant_trans_id)
    student_res = await db.execute(select(User).where(User.id == student_id))
    student = student_res.scalar_one_or_none()
    if not student:
        return {"error": -5, "error_note": "User not found"}

    if action == 0:
        return {
            "click_trans_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "merchant_prepare_id": click_trans_id,
            "error": 0,
            "error_note": "Success"
        }
    elif action == 1:
        from datetime import date
        current_month = date.today().strftime("%Y-%m")
        payment = Payment(
            student_id=student.id,
            amount=amount,
            payment_method=PaymentMethod.CLICK,
            transaction_id=click_trans_id,
            month_for=current_month,
            note="Click Merchant online to'lov"
        )
        db.add(payment)
        await db.commit()
        await db.refresh(payment)

        # Billing sinxronizatsiyasi
        from app.api.v1.finance import sync_student_billing
        await sync_student_billing(db, student.id, current_month)
        await db.commit()

        # Telegramga rasmiy to'lov chekini yuborish
        from app.services.notification import send_telegram_notification
        payment_time_str = payment.created_at.strftime('%Y-%m-%d %H:%M') if hasattr(payment, 'created_at') and payment.created_at else date.today().strftime('%Y-%m-%d')
        tg_msg = (
            f"🧾 <b>RASMIY TO'LOV CHEKI #{payment.id} (CLICK)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏢 <b>Ta'lim Plus Education Center</b>\n"
            f"👤 O'quvchi: <b>{student.full_name}</b> (ID: <code>{student.login_id}</code>)\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 <b>To'langan summa: {payment.amount:,.0f} so'm</b>\n"
            f"💳 To'lov turi: <b>CLICK (Tranzaksiya: {click_trans_id})</b>\n"
            f"📅 To'lov oyi: <b>{payment.month_for}</b>\n"
            f"🕒 Sana va vaqt: <b>{payment_time_str}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ <i>To'lovingiz muvaffaqiyatli qabul qilindi. Ta'lim Plus'ni tanlaganingiz uchun tashakkur!</i>"
        )

        if student.telegram_chat_id:
            await send_telegram_notification(student.telegram_chat_id, tg_msg)

        logger.info(f"Click to'lov qabul qilindi va chek yuborildi: student_id={student.id}, amount={amount}")
        return {
            "click_trans_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "merchant_confirm_id": payment.id,
            "error": 0,
            "error_note": "Success"
        }
    
    return {"error": -3, "error_note": "Action not found"}
