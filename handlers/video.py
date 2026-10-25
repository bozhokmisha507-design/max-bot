import logging
import os
import uuid

from config import Config
from max_client import MaxClient
from keyboards import main_menu_keyboard
from services.aitunnel import AITunnelService
from fsm import fsm

logger = logging.getLogger(__name__)

STATE_PHOTO = "video:photo"
STATE_PROMPT = "video:prompt"
MAX_PHOTOS = 3

VIDEO_MODELS = {
    "sora2pro": {
        "name": "🎬 Sora 2 Pro",
        "price_rub": Config.VIDEO_PRICE,
        "price_tokens": Config.VIDEO_TOKEN_COST,
        "duration": 4, "size": "1280x720", "api_model": "sora-2-pro",
    },
    "wan27": {
        "name": "⚡ Wan 2.7",
        "price_rub": Config.VIDEO_PRICE_LITE,
        "price_tokens": Config.VIDEO_TOKEN_COST_LITE,
        "duration": 4, "size": "1280x720", "api_model": "wan-2.7",
    },
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


async def video_start(client: MaxClient, user_id: int, chat_id: int | None):
    fsm.update(user_id, video_photos=[])
    fsm.set_state(user_id, STATE_PHOTO)
    await client.send_message(
        user_id=user_id, chat_id=chat_id,
        text=(f"🎬 Создание видео\n\n"
              f"Загрузите до {MAX_PHOTOS} селфи (минимум одно).\n"
              f"После каждого фото появится кнопка «Готово»."),
        attachments=[{"type": "inline_keyboard", "payload": {"buttons": [
            [{"type": "callback", "text": "✅ Готово", "payload": "video_done"}],
            [{"type": "callback", "text": "❌ Отмена", "payload": "video_cancel"}],
        ]}}],
    )


async def handle_photo(client: MaxClient, user_id: int, chat_id: int | None,
                        message: dict, db):
    url = _extract_image_url(message)
    if not url:
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                  text="Пожалуйста, отправьте фото.")
        return

    user_dir = os.path.join(Config.UPLOAD_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    path = os.path.join(user_dir, f"video_{uuid.uuid4().hex[:8]}.jpg")
    await client.download_attachment(url, path)

    photos = fsm.get(user_id).setdefault("video_photos", [])
    photos.append(path)
    count = len(photos)

    if count >= MAX_PHOTOS:
        fsm.set_state(user_id, STATE_PROMPT)
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                  text=f"✅ Загружено {MAX_PHOTOS} фото. Введите описание видео.")
    else:
        await client.send_message(
            user_id=user_id, chat_id=chat_id,
            text=f"✅ Фото {count}/{MAX_PHOTOS}. Отправьте ещё или нажмите «Готово».",
            attachments=[{"type": "inline_keyboard", "payload": {"buttons": [
                [{"type": "callback", "text": "✅ Готово", "payload": "video_done"}],
                [{"type": "callback", "text": "❌ Отмена", "payload": "video_cancel"}],
            ]}}],
        )


async def handle_done(client: MaxClient, user_id: int, chat_id: int | None, callback_id: str):
    photos = fsm.get(user_id).get("video_photos") or []
    if not photos:
        await client.answer_callback(callback_id, text="❌ Нет фото. Начните заново.")
        fsm.clear(user_id)
        return
    fsm.set_state(user_id, STATE_PROMPT)
    await client.answer_callback(callback_id, text="✅ Введите описание видео.")


async def handle_prompt(client: MaxClient, user_id: int, chat_id: int | None, text: str):
    fsm.update(user_id, video_prompt=text.strip())
    fsm.set_state(user_id, None)

    buttons = []
    for key, info in VIDEO_MODELS.items():
        buttons.append([{"type": "callback",
                         "text": f"{info['name']} – {info['price_rub']}₽ / {info['price_tokens']} жет.",
                         "payload": f"video_model_{key}"}])
    buttons.append([{"type": "callback", "text": "❌ Отмена", "payload": "video_cancel"}])

    await client.send_message(
        user_id=user_id, chat_id=chat_id,
        text="🎬 Выберите модель:",
        attachments=[{"type": "inline_keyboard", "payload": {"buttons": buttons}}],
    )


async def handle_model_callback(client: MaxClient, user_id: int, chat_id: int | None,
                                 callback_id: str, payload: str, db):
    key = payload.replace("video_model_", "")
    if key not in VIDEO_MODELS:
        await client.answer_callback(callback_id, text="❌ Неизвестная модель.")
        return
    info = VIDEO_MODELS[key]
    fsm.update(user_id, video_model=key)

    tokens = await db.get_user_tokens(user_id)
    buttons = []
    if tokens >= info["price_tokens"]:
        buttons.append([{"type": "callback",
                         "text": f"💎 Жетоны ({info['price_tokens']} шт.)",
                         "payload": "video_pay_tokens"}])
    buttons.append([{"type": "callback",
                     "text": f"💳 Оплатить {info['price_rub']}₽",
                     "payload": "video_pay_money"}])
    buttons.append([{"type": "callback", "text": "❌ Отмена", "payload": "video_cancel"}])

    await client.answer_callback(
        callback_id,
        text=f"✅ Модель: {info['name']}\nДлительность: {info['duration']}с\n\nКак оплатить?",
        attachments=[{"type": "inline_keyboard", "payload": {"buttons": buttons}}],
    )


async def pay_with_tokens(client: MaxClient, user_id: int, chat_id: int | None,
                          callback_id: str, db):
    model_key = fsm.get(user_id).get("video_model")
    if not model_key:
        await client.answer_callback(callback_id, text="❌ Модель не выбрана.")
        return
    cost = VIDEO_MODELS[model_key]["price_tokens"]
    if not await db.use_tokens(user_id, cost):
        await client.answer_callback(callback_id, text="❌ Недостаточно жетонов.")
        return
    fsm.update(user_id, video_paid_with_tokens=True, video_token_cost=cost)
    await client.answer_callback(callback_id, text="⏳ Генерация видео...")
    await generate_video(client, user_id, chat_id, db)


async def pay_with_money(client: MaxClient, user_id: int, chat_id: int | None,
                          callback_id: str, db):
    data_state = fsm.get(user_id)
    model_key = data_state.get("video_model")
    prompt = data_state.get("video_prompt")
    photos = data_state.get("video_photos") or []
    if not model_key or not prompt or not photos:
        await client.answer_callback(callback_id, text="❌ Данные неполные.")
        return

    info = VIDEO_MODELS[model_key]
    label = f"video_{user_id}_{uuid.uuid4().hex[:8]}"
    await db.create_order(user_id, label, info["price_rub"], data={
        "prompt": prompt, "model": model_key,
        "duration": info["duration"], "size": info["size"],
        "api_model": info["api_model"], "photos": photos,
    })

    from services import yookassa_service
    try:
        payment_id, url = yookassa_service.create_payment(
            info["price_rub"], f"Генерация видео {info['name']}", label, user_id,
        )
        await db.update_order_payment_id(label, payment_id)
    except Exception as e:
        logger.error(f"Ошибка платежа: {e}")
        await client.answer_callback(callback_id, text="❌ Не удалось создать ссылку.")
        return

    buttons = [[{"type": "link", "text": f"💳 Оплатить {info['price_rub']}₽", "url": url}]]
    await client.answer_callback(
        callback_id,
        text="✨ Нажмите кнопку. После оплаты видео придёт автоматически.",
        attachments=[{"type": "inline_keyboard", "payload": {"buttons": buttons}}],
    )


async def cancel(client: MaxClient, user_id: int, chat_id: int | None, callback_id: str):
    data = fsm.get(user_id)
    for p in data.get("video_photos") or []:
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass
    fsm.clear(user_id)
    await client.answer_callback(callback_id, text="❌ Отменено.",
                                  attachments=main_menu_keyboard())


async def _do_generate(client: MaxClient, user_id: int, chat_id: int | None,
                       prompt: str, model_key: str, photos: list):
    info = VIDEO_MODELS.get(model_key, VIDEO_MODELS["sora2pro"])
    aitunnel = AITunnelService()
    if model_key == "sora2pro":
        video_bytes = await aitunnel.generate_video_sora_i2v(
            image_paths=photos, prompt=prompt,
            size=info["size"], duration=info["duration"],
        )
    elif model_key == "wan27":
        video_bytes = await aitunnel.generate_video_wan27(
            prompt=prompt, size=info["size"], duration=info["duration"],
            image_paths=photos,
        )
    else:
        return None
    if not video_bytes:
        return None
    from handlers.payment import send_video
    await client.send_message(user_id=user_id, chat_id=chat_id, text="✅ Видео готово!")
    await send_video(client, user_id=user_id, chat_id=chat_id, video_bytes=video_bytes)
    return True


async def generate_video(client: MaxClient, user_id: int, chat_id: int | None, db):
    data = fsm.get(user_id)
    prompt = data.get("video_prompt")
    model_key = data.get("video_model", "sora2pro")
    photos = data.get("video_photos") or []
    if not prompt or not photos:
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                  text="❌ Нет промпта или фото.")
        return

    ok = await _do_generate(client, user_id, chat_id, prompt, model_key, photos)
    if not ok:
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                  text="❌ Не удалось сгенерировать видео.")
        if data.get("video_paid_with_tokens"):
            cost = data.get("video_token_cost") or VIDEO_MODELS[model_key]["price_tokens"]
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


async def generate_video_from_data(client: MaxClient, user_id: int, db, data: dict):
    prompt = data.get("prompt")
    model_key = data.get("model", "sora2pro")
    photos = data.get("photos") or []
    if not prompt or not photos:
        await client.send_message(user_id=user_id, text="❌ Неполные данные.")
        return
    ok = await _do_generate(client, user_id, None, prompt, model_key, photos)
    if ok:
        for p in photos:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
        await client.send_message(user_id=user_id, text="👇 Главное меню:",
                                  attachments=main_menu_keyboard())