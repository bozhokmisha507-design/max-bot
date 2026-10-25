import logging

from config import Config
from max_client import MaxClient
from keyboards import main_menu_keyboard, back_to_menu_keyboard

logger = logging.getLogger(__name__)

MAIN_MENU_TEXT = (
    "📌 *Главное меню*\n\n"
    "Выберите действие:"
)

HELP_TEXT = (
    "❓ *Помощь*\n\n"
    "Я умею создавать фото и видео по вашим селфи.\n\n"
    "1. Загрузите несколько селфи через «📤 Загрузить фото»\n"
    "2. Выберите стиль через «🖼️ Стили»\n"
    "3. Оплатите генерацию или используйте жетоны\n\n"
    "По вопросам: @support"
)


async def handle_start(client: MaxClient, user_id: int, chat_id: int | None,
                       db, first_name: str = ""):
    await db.get_or_create_user(user_id, first_name=first_name)
    text = (
        f"👋 Привет, {first_name or 'друг'}!\n\n"
        "Добро пожаловать в *PIXEL AI* — бот для создания фотографий и видео "
        "по вашим селфи.\n\n"
        "👇 Нажмите кнопку ниже, чтобы начать."
    )
    await client.send_message(
        chat_id=chat_id, user_id=user_id,
        text=text,
        attachments=main_menu_keyboard(),
    )


async def handle_menu(client: MaxClient, user_id: int, chat_id: int | None):
    await client.send_message(
        chat_id=chat_id, user_id=user_id,
        text=MAIN_MENU_TEXT,
        attachments=main_menu_keyboard(),
    )


async def handle_help(client: MaxClient, user_id: int, chat_id: int | None):
    await client.send_message(
        chat_id=chat_id, user_id=user_id,
        text=HELP_TEXT,
        attachments=back_to_menu_keyboard(),
    )