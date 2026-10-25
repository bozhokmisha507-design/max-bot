import logging

from config import Config
from max_client import MaxClient
from keyboards import (
    styles_keyboard, model_select_keyboard, pay_method_keyboard,
    back_to_menu_keyboard, main_menu_keyboard,
)
from fsm import fsm

logger = logging.getLogger(__name__)


async def show_styles_menu(client: MaxClient, user_id: int, chat_id: int | None,
                            *, callback_id: str | None = None):
    text = (
        "🎨 *Выберите стиль фотосессии:*\n\n"
        "Нажмите на кнопку с нужным стилем:"
    )
    att = styles_keyboard()
    if callback_id:
        await client.answer_callback(callback_id, text=text, attachments=att)
    else:
        await client.send_message(chat_id=chat_id, user_id=user_id,
                                  text=text, attachments=att)


async def handle_style_selected(client: MaxClient, user_id: int, chat_id: int | None,
                                 callback_id: str, payload: str, db):
    style_key = payload.replace("select_style_", "")
    style = Config.STYLES.get(style_key)
    if not style:
        await client.answer_callback(callback_id, text="❌ Неизвестный стиль.")
        return

    photo_count = await db.get_user_photo_count(user_id)
    if photo_count < Config.MIN_PHOTOS:
        await client.answer_callback(
            callback_id,
            text=(
                f"⚠️ Нужно минимум {Config.MIN_PHOTOS} фото. Сейчас: {photo_count}\n\n"
                f"Нажмите «📤 Загрузить фото» в главном меню."
            ),
            attachments=back_to_menu_keyboard(),
        )
        return

    await db.set_user_selected_style(user_id, style_key)
    fsm.update(user_id, selected_style=style_key)

    await client.answer_callback(
        callback_id,
        text=(
            f"✅ Стиль «{style['name']}» выбран.\n\n"
            "Теперь выберите качество генерации:"
        ),
        attachments=model_select_keyboard(),
    )


async def handle_model_selected(client: MaxClient, user_id: int, chat_id: int | None,
                                 callback_id: str, payload: str, db):
    choice = payload.replace("select_model_", "")
    if choice == "gemini":
        price, token_cost, model_name = (
            Config.PRICE_PER_GENERATION, Config.TOKEN_COST_GEMINI, "Gemini",
        )
    elif choice == "gpt":
        price, token_cost, model_name = (
            Config.PRICE_PREMIUM, Config.TOKEN_COST_GPT, "GPT Image High",
        )
    elif choice == "nanobanana":
        price, token_cost, model_name = (
            Config.PRICE_NANOBANANA, Config.TOKEN_COST_NANOBANANA, "Nano Banana Pro",
        )
    else:
        await client.answer_callback(callback_id, text="❌ Неизвестная модель.")
        return

    fsm.update(user_id, selected_model=choice)
    tokens = await db.get_user_tokens(user_id)

    await client.answer_callback(
        callback_id,
        text=(
            f"✅ Выбрано: *{model_name}*\n"
            f"Цена: {price}₽ или {token_cost} жетон(ов).\n\n"
            f"Как хотите получить фото?"
        ),
        attachments=pay_method_keyboard(tokens, token_cost, price),
    )


async def generate_photo_with_tokens(client: MaxClient, user_id: int, chat_id: int | None,
                                      db, style_key: str, model: str):
    """Генерация по жетонам."""
    if model == "gemini":
        cost = Config.TOKEN_COST_GEMINI
    elif model == "gpt":
        cost = Config.TOKEN_COST_GPT
    elif model == "nanobanana":
        cost = Config.TOKEN_COST_NANOBANANA
    else:
        return

    if not await db.use_tokens(user_id, cost):
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                   text="❌ Недостаточно жетонов.")
        return

    from services.aitunnel import AITunnelService
    from handlers.payment import send_image

    style = Config.STYLES.get(style_key)
    if not style:
        await db.add_tokens(user_id, cost)
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                   text="❌ Стиль не найден.")
        return

    photo_paths = await db.get_user_photos(user_id, "input")
    if not photo_paths:
        await db.add_tokens(user_id, cost)
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                   text="❌ Загрузите фото.")
        return

    gender = await db.get_user_gender(user_id)

    if model == "gemini":
        service = AITunnelService(model_type="gemini")
    elif model == "gpt":
        service = AITunnelService(model_type="gpt", quality="high", size="1024x1024")
    else:
        service = AITunnelService(model_type="nanobanana")

    try:
        results = await service.generate_photos(photo_paths, style_key, 1, gender)
    except Exception as e:
        logger.error(f"Ошибка генерации: {e}", exc_info=True)
        results = []

    if not results:
        await db.add_tokens(user_id, cost)
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                   text=f"⚠️ Ошибка. Возвращено {cost} жетонов.")
        return

    await client.send_message(user_id=user_id, chat_id=chat_id,
                              text=f"✅ Фото в стиле {style['name']}:")
    for img in results:
        await send_image(client, user_id=user_id, chat_id=chat_id, image_data=img)
    await client.send_message(user_id=user_id, chat_id=chat_id,
                              text="👇 Главное меню:", attachments=main_menu_keyboard())