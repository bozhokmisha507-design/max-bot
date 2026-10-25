import logging
import uuid

from yookassa import Configuration, Payment

from config import Config

logger = logging.getLogger(__name__)

Configuration.account_id = Config.YKASSA_SHOP_ID
Configuration.secret_key = Config.YKASSA_SECRET_KEY


def create_payment(amount: float, description: str, label: str, user_id: int) -> str:
    """Создаёт платёж ЮKassa и возвращает URL подтверждения."""
    payment = Payment.create({
        "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
        "capture": True,
        "confirmation": {
            "type": "redirect",
            "return_url": Config.YKASSA_RETURN_URL,
        },
        "description": description,
        "metadata": {"label": label, "user_id": user_id},
    }, uuid.uuid4())
    return payment.id, payment.confirmation.confirmation_url