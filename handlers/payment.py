import base64
import logging
import os
import tempfile
import uuid

from config import Config
from max_client import MaxClient
from keyboards import payment_link_keyboard, main_menu_keyboard
from services import yookassa_service
from services.aitunnel import AITunnelService

logger = logging.getLogger(__name__)


async def send_image(client: MaxClient, *, user_id: int, chat_id: int | None,
                     image_data: str, caption: str = ""):
    """Отправляет изображение (URL или data:base64) через MAX."""
    file_path = None
    try:
        if image_data.startswith("data:image"):
            _, b64 = image_data.split(",", 1)
            raw = base64.b64decode(b64)
            fd, file_path = tempfile.mkstemp(suffix=".jpg")
            os.close(fd)
            with open(file_path, "wb") as f:
                f.write(raw)
        elif image_data.startswith("http"):
            fd, file_path = tempfile.mkstemp(suffix=".jpg")
            os.close(fd)
            await client.download_attachment(image_data, file_path)
        else:
            logger.warning("Неизвестный формат изображения")
            return

        await client.send_photo(user_id=user_id, chat_id=chat_id,
                                file_path=file_path, text=caption)
    except Exception as e:
        logger.error(f"Ошибка отправки изображения: {e}", exc_info=True)
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)


async def send_video(client: MaxClient, *, user_id: int, chat_id: int | None,
                     video_bytes: bytes, caption: str = ""):
    file_path = None
    try:
        fd, file_path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        with open(file_path, "wb") as f:
            f.write(video_bytes)
        await client.send_video(user_id=user_id, chat_id=chat_id,
                                file_path=file_path, text=caption)
    except Exception as e:
        logger.error(f"Ошибка отправки видео: {e}", exc_info=True)
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)


async def create_single_payment(client: MaxClient, *, user_id: int, chat_id: int,
                                 db, style_key: str, model: str):
    if model == "gpt":
        amount = Config.PRICE_PREMIUM
    elif model == "nanobanana":
        amount = Config.PRICE_NANOBANANA
    else:
        amount = Config.PRICE_PER_GENERATION

    label = f"single_{user_id}_{uuid.uuid4().hex[:8]}"
    await db.create_order(user_id, label, amount,
                          data={"selected_model": model, "style_key": style_key})

    try:
        payment_id, url = yookassa_service.create_payment(
            amount, "Оплата генерации фото в PIXEL AI", label, user_id,
        )
        await db.update_order_payment_id(label, payment_id)
    except Exception as e:
        logger.error(f"Ошибка создания платежа: {e}", exc_info=True)
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                  text="❌ Не удалось создать ссылку на оплату.",
                                  attachments=main_menu_keyboard())
        return

    await client.send_message(
        user_id=user_id, chat_id=chat_id,
        text=f"✨ Стоимость генерации: {amount}₽\n\n👇 Нажмите кнопку для оплаты:",
        attachments=payment_link_keyboard(url, amount),
    )


async def create_tokens_payment(client: MaxClient, *, user_id: int, chat_id: int, db):
    amount = Config.PRICE_20_TOKENS
    label = f"tokens20_{user_id}_{uuid.uuid4().hex[:8]}"
    await db.create_order(user_id, label, amount, data={"token_pack": 20})

    try:
        payment_id, url = yookassa_service.create_payment(
            amount, "Пакет 20 жетонов в PIXEL AI", label, user_id,
        )
        await db.update_order_payment_id(label, payment_id)
    except Exception as e:
        logger.error(f"Ошибка создания платежа: {e}", exc_info=True)
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                  text="❌ Не удалось создать ссылку.",
                                  attachments=main_menu_keyboard())
        return

    await client.send_message(
        user_id=user_id, chat_id=chat_id,
        text=f"✨ Купи пакет из 20 жетонов!\nСтоимость: {amount}₽",
        attachments=payment_link_keyboard(url, amount),
    )


async def generate_paid_photo(client: MaxClient, *, user_id: int, chat_id: int | None,
                              db, label: str, order_data: dict):
    if await db.is_order_processed(label):
        logger.info(f"Заказ {label} уже обработан")
        return

    model = order_data.get("selected_model", "gemini")
    style_key = order_data.get("style_key")
    style = Config.STYLES.get(style_key) if style_key else None
    if not style:
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                  text="❌ Стиль не найден.")
        return

    photo_paths = await db.get_user_photos(user_id, "input")
    if not photo_paths:
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                  text="❌ Не найдены фото. Загрузите через «📤 Загрузить фото».")
        return

    gender = await db.get_user_gender(user_id)

    if model == "gemini":
        service = AITunnelService()
    elif model == "gpt":
        service = AITunnelService(model_type="gpt", quality="high", size="1536x1024")
    elif model == "nanobanana":
        service = AITunnelService(model_type="nanobanana")
    else:
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                  text="❌ Неизвестная модель.")
        return

    results = await service.generate_photos(
        user_photo_paths=photo_paths, style_key=style_key,
        num_images=1, gender=gender,
    )

    if not results:
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                  text="❌ Не удалось сгенерировать. Если деньги списаны — вернутся.")
        return

    await client.send_message(user_id=user_id, chat_id=chat_id,
                              text=f"✅ Оплата получена! Фото в стиле {style['name']}:")
    for img in results:
        await send_image(client, user_id=user_id, chat_id=chat_id, image_data=img)

    await db.mark_order_processed(label)
    await client.send_message(user_id=user_id, chat_id=chat_id,
                              text="👇 Главное меню:", attachments=main_menu_keyboard())


async def process_yookassa_webhook(data: dict, client: MaxClient, db):
    """Обработка события payment.succeeded от ЮKassa."""
    if data.get("event") != "payment.succeeded":
        return
    payment = data.get("object") or {}
    label = (payment.get("metadata") or {}).get("label")
    if not label:
        logger.warning("Нет label в уведомлении")
        return

    if await db.is_order_processed(label):
        logger.info(f"Заказ {label} уже обработан")
        return

    user_id = (payment.get("metadata") or {}).get("user_id")
    if not user_id:
        parts = label.split("_")
        if len(parts) > 1 and parts[1].isdigit():
            user_id = int(parts[1])
    if not user_id:
        logger.error(f"Не удалось определить user_id для {label}")
        return

    if label.startswith("tokens20_"):
        await db.add_tokens(user_id, 20)
        await client.send_message(user_id=user_id,
                                  text="✅ Вам начислено 20 жетонов!")
        await db.mark_order_processed(label)

    elif label.startswith("couple_"):
        order_data = await db.get_order_data(label)
        if order_data:
            from handlers.couple import generate_couple_photo_from_data
            try:
                await generate_couple_photo_from_data(client, user_id, db, order_data)
            except Exception as e:
                logger.error(f"Ошибка генерации пары: {e}", exc_info=True)
                await db.add_tokens(user_id, Config.COUPLE_TOKEN_COST)
                await client.send_message(user_id=user_id,
                                          text=f"⚠️ Ошибка. Возвращено {Config.COUPLE_TOKEN_COST} жетонов.")
            finally:
                await db.mark_order_processed(label)

    elif label.startswith("custom_"):
        order_data = await db.get_order_data(label)
        if order_data:
            from handlers.custom_prompt import generate_custom_photo_from_data
            try:
                await generate_custom_photo_from_data(client, user_id, db, order_data)
            except Exception as e:
                logger.error(f"Ошибка кастомной генерации: {e}", exc_info=True)
                await db.add_tokens(user_id, Config.TOKEN_COST_GPT)
                await client.send_message(user_id=user_id,
                                          text=f"⚠️ Ошибка. Возвращено {Config.TOKEN_COST_GPT} жетонов.")
            finally:
                await db.mark_order_processed(label)

    elif label.startswith("video_"):
        order_data = await db.get_order_data(label)
        if order_data:
            from handlers.video import generate_video_from_data, VIDEO_MODELS
            try:
                await generate_video_from_data(client, user_id, db, order_data)
            except Exception as e:
                logger.error(f"Ошибка генерации видео: {e}", exc_info=True)
                model_key = order_data.get("model", "sora2pro")
                token_cost = VIDEO_MODELS.get(model_key, {}).get("price_tokens", 8)
                await db.add_tokens(user_id, token_cost)
                await client.send_message(user_id=user_id,
                                          text=f"⚠️ Ошибка. Возвращено {token_cost} жетонов.")
            finally:
                await db.mark_order_processed(label)

    else:  # single_
        order_data = await db.get_order_data(label)
        if not order_data:
            logger.error(f"Нет данных для {label}")
            return
        try:
            await generate_paid_photo(client, user_id=user_id, chat_id=None,
                                      db=db, label=label, order_data=order_data)
        except Exception as e:
            logger.error(f"Ошибка генерации single: {e}", exc_info=True)
            model = order_data.get("selected_model", "gemini")
            tokens = (Config.TOKEN_COST_GEMINI if model == "gemini"
                      else Config.TOKEN_COST_GPT if model == "gpt"
                      else Config.TOKEN_COST_NANOBANANA)
            await db.add_tokens(user_id, tokens)
            await client.send_message(user_id=user_id,
                                      text=f"⚠️ Ошибка. Возвращено {tokens} жетонов.")
            await db.mark_order_processed(label)