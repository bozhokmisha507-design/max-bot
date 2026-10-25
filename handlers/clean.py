import logging
import os

from config import Config
from max_client import MaxClient
from keyboards import main_menu_keyboard

logger = logging.getLogger(__name__)


async def handle_clean(client: MaxClient, user_id: int, chat_id: int | None, db):
    photo_paths = await db.get_user_photos(user_id, "input")
    if not photo_paths:
        await client.send_message(
            chat_id=chat_id, user_id=user_id,
            text="📭 У вас нет сохранённых фото.",
            attachments=main_menu_keyboard(),
        )
        return

    deleted = 0
    for path in photo_paths:
        try:
            if os.path.exists(path):
                os.remove(path)
                deleted += 1
        except Exception as e:
            logger.warning(f"Ошибка удаления {path}: {e}")

    user_dir = os.path.join(Config.UPLOAD_DIR, str(user_id))
    try:
        if os.path.exists(user_dir) and not os.listdir(user_dir):
            os.rmdir(user_dir)
    except Exception:
        pass

    await db.clear_user_photos(user_id)

    await client.send_message(
        chat_id=chat_id, user_id=user_id,
        text=f"✅ Очищено {deleted} фото. Можете загрузить новые.",
        attachments=main_menu_keyboard(),
    )