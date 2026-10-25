import logging

from config import Config
from max_client import MaxClient
from keyboards import main_menu_keyboard

logger = logging.getLogger(__name__)


async def handle_tokens(client: MaxClient, user_id: int, chat_id: int | None, db):
    tokens = await db.get_user_tokens(user_id)
    text = (
        f"💎 *Ваш баланс жетонов:* {tokens}\n\n"
        "• Gemini = 1 жетон\n"
        "• GPT Image High = 2 жетона\n"
        "• Nano Banana Pro = 2 жетона\n"
        "• Парные фото = 2 жетона\n"
        "• Видео Sora 2 Pro = 8 жетонов\n"
        "• Wan 2.7 (видео) = 4 жетона"
    )
    buttons = [[{
        "type": "callback",
        "text": f"💎 Купить 20 жетонов за {Config.PRICE_20_TOKENS}₽",
        "payload": "buy_tokens",
    }]]
    await client.send_message(
        chat_id=chat_id, user_id=user_id,
        text=text,
        attachments=[{"type": "inline_keyboard", "payload": {"buttons": buttons}}],
    )