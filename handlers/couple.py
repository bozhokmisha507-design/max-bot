import asyncio
import logging
import os
import uuid

import aiohttp

from config import Config
from max_client import MaxClient
from keyboards import main_menu_keyboard
from services.aitunnel import AITunnelService
from fsm import fsm

logger = logging.getLogger(__name__)

STATE_MALE = "couple:male"
STATE_FEMALE = "couple:female"

COUPLE_STYLES = {
    "couple_beach": "🏖️ Романтический пляж",
    "couple_wedding": "💒 Свадебное фото",
    "couple_dinner": "🕯️ Романтический ужин",
    "couple_city": "🌃 Вечерний город",
    "couple_forest": "🌲 Лесная прогулка",
}

COUPLE_PROMPTS = {
    "couple_beach": "A romantic close-up portrait of a couple on a beach at sunset, holding hands, embracing, photorealistic, 8k, highly detailed faces, exact facial features as in reference images, faces clearly visible, sharp focus on faces, medium shot, warm sunset lighting",
    "couple_wedding": "A romantic close-up wedding portrait of a couple in a garden, bride in elegant white dress, groom in classic tuxedo, photorealistic, 8k, highly detailed faces, exact facial features as in reference images, faces clearly visible, sharp focus on faces, soft romantic lighting, shallow depth of field, professional wedding photography style",
    "couple_dinner": "A romantic close-up portrait of a couple having a romantic dinner in a cozy restaurant, candlelight, photorealistic, 8k, highly detailed faces, exact facial features as in reference images, faces clearly visible, sharp focus on faces, warm intimate lighting, professional photography style",
    "couple_city": "A romantic close-up portrait of a couple in love standing on a rooftop at night, city lights background, cinematic, photorealistic, 8k, highly detailed faces, exact facial features as in reference images, faces clearly visible, sharp focus on faces, medium shot, professional night photography style",
    "couple_forest": "A romantic close-up portrait of a couple walking in a sunlit forest, holding hands, warm lighting, photorealistic, 8k, highly detailed faces, exact facial features as in reference images, faces clearly visible, sharp focus on faces, medium shot, professional nature photography style, sun rays filtering through trees",
}


def _extract_image_url(message: dict) -> str | None:
    body = message.get("body") or {}
    attachments = body.get("attachments") or message.get("attachments") or []
    for att in attachments:
        if att.get("type") in ("image", "photo"):
            payload = att.get("payload") or {}
            url = payload.get("url") or payload.get("photo_url")
            if url:
                return url
    return None


async def couple_start(client: MaxClient, user_id: int, chat_id: int | None):
    fsm.update(user_id, couple_photos=[])
    fsm.set_state(user_id, STATE_MALE)
    await client.send_message(
        user_id=user_id, chat_id=chat_id,
        text=("👫 Парная генерация\n\n"
              "Сначала загрузите фото мужчины.\n"
              "После этого — фото женщины.\n\n"
              "Для отмены — /cancel"),
    )


async def handle_male_photo(client: MaxClient, user_id: int, chat_id: int | None,
                             message: dict, db):
    url = _extract_image_url(message)
    if not url:
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                  text="Пожалуйста, отправьте фото.")
        return

    user_dir = os.path.join(Config.UPLOAD_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    path = os.path.join(user_dir, f"couple_male_{uuid.uuid4().hex[:8]}.jpg")
    await client.download_attachment(url, path)

    fsm.get(user_id).setdefault("couple_photos", []).append(path)
    fsm.set_state(user_id, STATE_FEMALE)

    await client.send_message(user_id=user_id, chat_id=chat_id,
                              text="✅ Фото мужчины сохранено. Теперь фото женщины.")


async def handle_female_photo(client: MaxClient, user_id: int, chat_id: int | None,
                               message: dict, db):
    url = _extract_image_url(message)
    if not url:
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                  text="Пожалуйста, отправьте фото.")
        return

    user_dir = os.path.join(Config.UPLOAD_DIR, str(user_id))
    path = os.path.join(user_dir, f"couple_female_{uuid.uuid4().hex[:8]}.jpg")
    await client.download_attachment(url, path)

    fsm.get(user_id).setdefault("couple_photos", []).append(path)
    fsm.set_state(user_id, None)

    buttons = []
    for key, name in COUPLE_STYLES.items():
        buttons.append([{"type": "callback", "text": name, "payload": f"couple_style_{key}"}])
    buttons.append([{"type": "callback", "text": "❌ Отмена", "payload": "couple_cancel"}])

    await client.send_message(
        user_id=user_id, chat_id=chat_id,
        text="🎨 Выберите стиль для парного фото:",
        attachments=[{"type": "inline_keyboard", "payload": {"buttons": buttons}}],
    )


async def handle_style_callback(client: MaxClient, user_id: int, chat_id: int | None,
                                 callback_id: str, payload: str, db):
    style_key = payload.replace("couple_style_", "")
    fsm.update(user_id, couple_style=style_key)

    tokens = await db.get_user_tokens(user_id)
    price = Config.COUPLE_PRICE
    token_cost = Config.COUPLE_TOKEN_COST

    buttons = []
    if tokens >= token_cost:
        buttons.append([{"type": "callback",
                         "text": f"💎 Использовать жетоны ({token_cost} шт., у вас {tokens})",
                         "payload": "couple_pay_tokens"}])
    buttons.append([{"type": "callback",
                     "text": f"💳 Оплатить {price}₽",
                     "payload": "couple_pay_money"}])
    buttons.append([{"type": "callback", "text": "❌ Отмена", "payload": "couple_cancel"}])

    await client.answer_callback(
        callback_id,
        text=(f"✅ Выбран стиль: {COUPLE_STYLES.get(style_key, style_key)}\n\n"
              "Как хотите получить фото?"),
        attachments=[{"type": "inline_keyboard", "payload": {"buttons": buttons}}],
    )


async def pay_with_tokens(client: MaxClient, user_id: int, chat_id: int | None,
                          callback_id: str, db):
    token_cost = Config.COUPLE_TOKEN_COST
    if not await db.use_tokens(user_id, token_cost):
        await client.answer_callback(callback_id, text="❌ Недостаточно жетонов.")
        return

    fsm.update(user_id, couple_paid_with_tokens=True, couple_token_cost=token_cost)
    await client.answer_callback(callback_id, text="⏳ Генерация...")
    await generate_couple_photo(client, user_id, chat_id, db)


async def pay_with_money(client: MaxClient, user_id: int, chat_id: int | None,
                          callback_id: str, db):
    data_state = fsm.get(user_id)
    photos = data_state.get("couple_photos") or []
    style_key = data_state.get("couple_style")
    if len(photos) != 2 or not style_key:
        await client.answer_callback(callback_id, text="❌ Данные неполные, начните заново.")
        return

    label = f"couple_{user_id}_{uuid.uuid4().hex[:8]}"
    amount = Config.COUPLE_PRICE
    await db.create_order(user_id, label, amount,
                          data={"male_photo": photos[0],
                                "female_photo": photos[1],
                                "style": style_key})

    from services import yookassa_service
    try:
        payment_id, url = yookassa_service.create_payment(
            amount, "Парная генерация фото", label, user_id,
        )
        await db.update_order_payment_id(label, payment_id)
    except Exception as e:
        logger.error(f"Ошибка создания платежа: {e}", exc_info=True)
        await client.answer_callback(callback_id, text="❌ Не удалось создать ссылку.")
        return

    buttons = [[{"type": "link", "text": f"💳 Оплатить {amount}₽", "url": url}]]
    await client.answer_callback(
        callback_id,
        text="✨ Нажмите кнопку ниже. После оплаты фото придёт автоматически.",
        attachments=[{"type": "inline_keyboard", "payload": {"buttons": buttons}}],
    )


async def cancel(client: MaxClient, user_id: int, chat_id: int | None, callback_id: str):
    data = fsm.get(user_id)
    for path in data.get("couple_photos") or []:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
    fsm.clear(user_id)
    await client.answer_callback(callback_id, text="❌ Отменено.",
                                  attachments=main_menu_keyboard())


async def _do_generate(client: MaxClient, user_id: int, chat_id: int | None,
                       male_photo: str, female_photo: str, style_key: str):
    prompt = COUPLE_PROMPTS.get(style_key, "A romantic couple, photorealistic")
    aitunnel = AITunnelService()
    try:
        results = await aitunnel.generate_couple_photo_nanobanana(
            male_photo_path=male_photo,
            female_photo_path=female_photo,
            prompt=prompt, resolution="2K",
        )
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.error(f"Ошибка генерации пары: {e}")
        return None

    if not results:
        return None
    from handlers.payment import send_image
    await client.send_message(user_id=user_id, chat_id=chat_id,
                              text="✅ Ваше парное фото готово!")
    await send_image(client, user_id=user_id, chat_id=chat_id, image_data=results[0])
    return True


async def generate_couple_photo(client: MaxClient, user_id: int, chat_id: int | None, db):
    data = fsm.get(user_id)
    photos = data.get("couple_photos") or []
    style_key = data.get("couple_style")
    if len(photos) != 2 or not style_key:
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                  text="❌ Ошибка: нет фото или стиля.")
        return

    ok = await _do_generate(client, user_id, chat_id, photos[0], photos[1], style_key)
    if not ok:
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                  text="❌ Не удалось сгенерировать.")
        if data.get("couple_paid_with_tokens"):
            cost = data.get("couple_token_cost", Config.COUPLE_TOKEN_COST)
            await db.add_tokens(user_id, cost)
            await client.send_message(user_id=user_id, chat_id=chat_id,
                                      text=f"💎 Возвращено {cost} жетонов.")
        return

    for p in photos:
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass
    fsm.clear(user_id)
    await client.send_message(user_id=user_id, chat_id=chat_id,
                              text="👇 Главное меню:", attachments=main_menu_keyboard())


async def generate_couple_photo_from_data(client: MaxClient, user_id: int, db, data: dict):
    male_photo = data.get("male_photo")
    female_photo = data.get("female_photo")
    style_key = data.get("style")
    if not male_photo or not female_photo or not style_key:
        await client.send_message(user_id=user_id, text="❌ Ошибка данных заказа.")
        return
    if not os.path.exists(male_photo) or not os.path.exists(female_photo):
        await client.send_message(user_id=user_id, text="❌ Исходные фото не найдены.")
        return

    ok = await _do_generate(client, user_id, None, male_photo, female_photo, style_key)
    if ok:
        for p in [male_photo, female_photo]:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
        await client.send_message(user_id=user_id, text="👇 Главное меню:",
                                  attachments=main_menu_keyboard())