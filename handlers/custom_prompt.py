import logging
import os
import uuid

from config import Config
from max_client import MaxClient
from keyboards import main_menu_keyboard
from services.aitunnel import AITunnelService
from fsm import fsm

logger = logging.getLogger(__name__)

STATE_PROMPT = "custom:prompt"


async def custom_start(client: MaxClient, user_id: int, chat_id: int | None, db):
    photo_count = await db.get_user_photo_count(user_id)
    if photo_count < Config.MIN_PHOTOS:
        await client.send_message(
            user_id=user_id, chat_id=chat_id,
            text=f"⚠️ Нужно минимум {Config.MIN_PHOTOS} фото. Загрузите через «📤 Загрузить фото».",
            attachments=main_menu_keyboard(),
        )
        return

    tokens = await db.get_user_tokens(user_id)
    price = Config.PRICE_PREMIUM
    token_cost = Config.TOKEN_COST_GPT

    buttons = []
    if tokens >= token_cost:
        buttons.append([{"type": "callback",
                         "text": f"💎 Использовать жетоны ({token_cost} шт., у вас {tokens})",
                         "payload": "custom_pay_tokens"}])
    buttons.append([{"type": "callback",
                     "text": f"💳 Оплатить {price}₽",
                     "payload": "custom_pay_money"}])
    buttons.append([{"type": "callback", "text": "❌ Отмена", "payload": "custom_cancel"}])

    await client.send_message(
        user_id=user_id, chat_id=chat_id,
        text=(f"✍️ Свой промпт\n\n"
              f"Стоимость: {price}₽ или {token_cost} жетон(ов).\n\n"
              f"Как оплатить?"),
        attachments=[{"type": "inline_keyboard", "payload": {"buttons": buttons}}],
    )


async def ask_prompt(client: MaxClient, user_id: int, chat_id: int | None, callback_id: str):
    fsm.set_state(user_id, STATE_PROMPT)
    await client.answer_callback(
        callback_id,
        text="✍️ Опишите, что должно быть на фото. Например:\n«я в костюме космонавта на Марсе»",
    )


async def handle_prompt(client: MaxClient, user_id: int, chat_id: int | None,
                         text: str, db):
    prompt = text.strip()
    fsm.update(user_id, custom_prompt=prompt)
    fsm.set_state(user_id, None)

    await client.send_message(
        user_id=user_id, chat_id=chat_id,
        text="⏳ Генерация по вашему промпту...",
    )
    await _generate_custom(client, user_id, chat_id, db, prompt, paid_with_tokens=True)


async def pay_tokens(client: MaxClient, user_id: int, chat_id: int | None,
                      callback_id: str, db):
    cost = Config.TOKEN_COST_GPT
    if not await db.use_tokens(user_id, cost):
        await client.answer_callback(callback_id, text="❌ Недостаточно жетонов.")
        return
    fsm.update(user_id, custom_paid_tokens=cost)
    await ask_prompt(client, user_id, chat_id, callback_id)


async def pay_money(client: MaxClient, user_id: int, chat_id: int | None,
                     callback_id: str, db):
    await ask_prompt(client, user_id, chat_id, callback_id)


async def handle_custom_prompt_finished(client: MaxClient, user_id: int, chat_id: int | None, db):
    """Вызывается, когда пользователь ввёл промпт после выбора оплаты деньгами."""
    data = fsm.get(user_id)
    prompt = data.get("custom_prompt")
    if not prompt:
        return
    # Создание платежа по промпту
    label = f"custom_{user_id}_{uuid.uuid4().hex[:8]}"
    amount = Config.PRICE_PREMIUM
    await db.create_order(user_id, label, amount,
                          data={"prompt": prompt})

    from services import yookassa_service
    try:
        payment_id, url = yookassa_service.create_payment(
            amount, "Кастомная генерация фото", label, user_id,
        )
        await db.update_order_payment_id(label, payment_id)
    except Exception as e:
        logger.error(f"Ошибка создания платежа: {e}")
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                  text="❌ Не удалось создать ссылку.")
        return

    buttons = [[{"type": "link", "text": f"💳 Оплатить {amount}₽", "url": url}]]
    await client.send_message(
        user_id=user_id, chat_id=chat_id,
        text="✨ Нажмите кнопку. После оплаты фото придёт автоматически.",
        attachments=[{"type": "inline_keyboard", "payload": {"buttons": buttons}}],
    )


async def _generate_custom(client: MaxClient, user_id: int, chat_id: int | None,
                            db, prompt: str, paid_with_tokens: bool):
    photo_paths = await db.get_user_photos(user_id, "input")
    if not photo_paths:
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                  text="❌ Нет фото.")
        return

    service = AITunnelService(model_type="gpt", quality="high", size="1024x1024")
    try:
        results = await service.generate_custom_photo(
            user_photo_paths=photo_paths, prompt=prompt, num_images=1,
        )
    except Exception as e:
        logger.error(f"Ошибка кастомной генерации: {e}", exc_info=True)
        results = []

    if not results:
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                  text="❌ Не удалось сгенерировать.")
        if paid_with_tokens:
            data = fsm.get(user_id)
            cost = data.get("custom_paid_tokens", Config.TOKEN_COST_GPT)
            await db.add_tokens(user_id, cost)
            await client.send_message(user_id=user_id, chat_id=chat_id,
                                      text=f"💎 Возвращено {cost} жетонов.")
        fsm.clear(user_id)
        return

    from handlers.payment import send_image
    await client.send_message(user_id=user_id, chat_id=chat_id,
                              text="✅ Готово!")
    for img in results:
        await send_image(client, user_id=user_id, chat_id=chat_id, image_data=img)

    fsm.clear(user_id)
    await client.send_message(user_id=user_id, chat_id=chat_id,
                              text="👇 Главное меню:", attachments=main_menu_keyboard())


async def generate_custom_photo_from_data(client: MaxClient, user_id: int, db, data: dict):
    prompt = data.get("prompt")
    if not prompt:
        await client.send_message(user_id=user_id, text="❌ Нет промпта.")
        return
    await _generate_custom(client, user_id, None, db, prompt, paid_with_tokens=False)