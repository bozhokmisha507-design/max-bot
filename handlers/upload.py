import logging
import os
import uuid

from config import Config
from max_client import MaxClient
from keyboards import upload_done_keyboard, back_to_menu_keyboard, main_menu_keyboard
from fsm import fsm

logger = logging.getLogger(__name__)

STATE_WAIT_PHOTO = "upload:wait_photo"


async def handle_upload_start(client: MaxClient, user_id: int, chat_id: int | None, db):
    count = await db.get_user_photo_count(user_id)
    if count >= Config.MAX_PHOTOS:
        await client.send_message(
            chat_id=chat_id, user_id=user_id,
            text=(
                f"⚠️ У вас уже максимальное количество фото ({Config.MAX_PHOTOS}).\n"
                "Очистите старые через «🗑 Очистить селфи»."
            ),
            attachments=main_menu_keyboard(),
        )
        return

    fsm.update(user_id, upload_count=count)
    fsm.set_state(user_id, STATE_WAIT_PHOTO)

    await client.send_message(
        chat_id=chat_id, user_id=user_id,
        text=(
            f"📸 *Загрузка фото*\n\n"
            f"Отправьте от {Config.MIN_PHOTOS} до {Config.MAX_PHOTOS} селфи.\n"
            f"Сейчас загружено: {count}\n\n"
            f"Когда закончите — нажмите «✅ Готово»."
        ),
        attachments=upload_done_keyboard(),
    )


def _extract_image_url(message: dict) -> str | None:
    """Ищет URL картинки в attachments сообщения."""
    body = message.get("body") or {}
    attachments = body.get("attachments") or message.get("attachments") or []
    for att in attachments:
        if att.get("type") in ("image", "photo"):
            payload = att.get("payload") or {}
            url = payload.get("url") or payload.get("photo_url")
            if url:
                return url
    return None


async def handle_photo(client: MaxClient, user_id: int, chat_id: int | None,
                       message: dict, db):
    """Вызывается, когда пользователь присылает фото в состоянии upload:wait_photo."""
    data = fsm.get(user_id)
    count = data.get("upload_count", 0)

    if count >= Config.MAX_PHOTOS:
        await client.send_message(
            chat_id=chat_id, user_id=user_id,
            text=f"❌ Достигнут лимит ({Config.MAX_PHOTOS}).",
            attachments=back_to_menu_keyboard(),
        )
        fsm.clear(user_id)
        return

    url = _extract_image_url(message)
    if not url:
        await client.send_message(
            chat_id=chat_id, user_id=user_id,
            text="❌ Не удалось найти изображение в сообщении. Отправьте фото ещё раз.",
        )
        return

    user_dir = os.path.join(Config.UPLOAD_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    file_name = f"photo_{uuid.uuid4().hex[:8]}.jpg"
    file_path = os.path.join(user_dir, file_name)

    try:
        await client.download_attachment(url, file_path)
    except Exception as e:
        logger.error(f"Ошибка скачивания фото: {e}")
        await client.send_message(
            chat_id=chat_id, user_id=user_id,
            text="❌ Не удалось скачать фото. Попробуйте ещё раз.",
        )
        return

    await db.add_photo(user_id, file_id="", file_path=file_path, ptype="input")

    new_count = await db.get_user_photo_count(user_id)
    fsm.update(user_id, upload_count=new_count)
    remaining = Config.MAX_PHOTOS - new_count

    await client.send_message(
        chat_id=chat_id, user_id=user_id,
        text=(
            f"✅ Фото #{new_count} сохранено!\n"
            f"Загружено: {new_count}/{Config.MAX_PHOTOS}\n"
            f"Осталось: {remaining}"
        ),
        attachments=upload_done_keyboard(),
    )


async def handle_upload_done(client: MaxClient, user_id: int, chat_id: int | None,
                              callback_id: str, db):
    count = await db.get_user_photo_count(user_id)
    if count < Config.MIN_PHOTOS:
        await client.answer_callback(
            callback_id,
            text=f"⚠️ Нужно минимум {Config.MIN_PHOTOS} фото. Сейчас: {count}",
        )
        return

    fsm.clear(user_id)
    await client.answer_callback(
        callback_id,
        text=(
            f"✅ Загрузка завершена! У вас {count} фото.\n"
            "Теперь выберите стиль через «🖼️ Стили»."
        ),
        attachments=main_menu_keyboard(),
    )


async def handle_upload_cancel(client: MaxClient, user_id: int, chat_id: int | None,
                                callback_id: str):
    fsm.clear(user_id)
    await client.answer_callback(
        callback_id,
        text="❌ Загрузка отменена.",
        attachments=main_menu_keyboard(),
    )