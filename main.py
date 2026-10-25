import asyncio
import logging
import os

from config import Config
from database import get_db, close_db
from fsm import fsm
from keyboards import main_menu_keyboard
from max_client import MaxClient, build_ssl_context

import handlers.start as start_h
import handlers.menu as menu_h
import handlers.styles as styles_h
import handlers.upload as upload_h
import handlers.clean as clean_h
import handlers.payment as payment_h
import handlers.couple as couple_h
import handlers.video as video_h
import handlers.custom_prompt as custom_h
import handlers.admin as admin_h

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


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


async def handle_message(client: MaxClient, update: dict, db):
    message = update.get("message", {})
    sender = message.get("sender", {})
    recipient = message.get("recipient", {})
    chat_id = recipient.get("chat_id")
    user_id = sender.get("user_id")
    first_name = sender.get("first_name") or ""
    text = ((message.get("body") or {}).get("text") or "").strip()

    if not user_id:
        return

    await db.get_or_create_user(user_id, first_name=first_name)

    state = fsm.state(user_id)

    # --- FSM-состояния ---
    if state == upload_h.STATE_WAIT_PHOTO:
        if _extract_image_url(message):
            await upload_h.handle_photo(client, user_id, chat_id, message, db)
        else:
            await client.send_message(user_id=user_id, chat_id=chat_id,
                                       text="Отправьте фото или нажмите «Готово».")
        return
    if state == couple_h.STATE_MALE:
        await couple_h.handle_male_photo(client, user_id, chat_id, message, db)
        return
    if state == couple_h.STATE_FEMALE:
        await couple_h.handle_female_photo(client, user_id, chat_id, message, db)
        return
    if state == video_h.STATE_PHOTO:
        if _extract_image_url(message):
            await video_h.handle_photo(client, user_id, chat_id, message, db)
        else:
            await client.send_message(user_id=user_id, chat_id=chat_id,
                                       text="Отправьте фото или нажмите «Готово».")
        return
    if state == video_h.STATE_PROMPT:
        if text:
            await video_h.handle_prompt(client, user_id, chat_id, text)
        return
    if state == custom_h.STATE_PROMPT:
        if text:
            await custom_h.handle_prompt(client, user_id, chat_id, text, db)
        return
    if state == admin_h.STATE_ADD_USER:
        await admin_h.add_tokens_user(client, user_id, chat_id, text)
        return
    if state == admin_h.STATE_ADD_AMOUNT:
        await admin_h.add_tokens_amount(client, user_id, chat_id, text, db)
        return

    # --- Команды и меню ---
    if text in ("/start", "start"):
        await start_h.handle_start(client, user_id, chat_id, db, first_name)
    elif text in ("/menu", "Меню", "меню", "🏠 Главное меню"):
        await start_h.handle_menu(client, user_id, chat_id)
    elif text == "/help":
        await start_h.handle_help(client, user_id, chat_id)
    elif text == "📤 Загрузить фото":
        await upload_h.handle_upload_start(client, user_id, chat_id, db)
    elif text == "👫 Парные фото":
        await couple_h.couple_start(client, user_id, chat_id)
    elif text == "🖼️ Стили":
        await styles_h.show_styles_menu(client, user_id, chat_id)
    elif text == "💎 Мои жетоны":
        await menu_h.handle_tokens(client, user_id, chat_id, db)
    elif text == "🗑 Очистить селфи":
        await clean_h.handle_clean(client, user_id, chat_id, db)
    elif text == "✍️ Свой промпт":
        await custom_h.custom_start(client, user_id, chat_id, db)
    elif text == "🎬 Создать видео":
        await video_h.video_start(client, user_id, chat_id)
    elif text == "❓ Помощь":
        await start_h.handle_help(client, user_id, chat_id)
    elif text == "/cancel":
        fsm.clear(user_id)
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                   text="Отменено.", attachments=main_menu_keyboard())
    elif text.startswith("/add_tokens"):
        await admin_h.add_tokens_start(client, user_id, chat_id)
    elif text.startswith("/broadcast"):
        args = text[len("/broadcast"):].strip()
        await admin_h.broadcast(client, user_id, chat_id, args, db)
    else:
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                   text=f"Не понимаю: {text[:50]}. Нажмите /menu.")


async def handle_callback(client: MaxClient, update: dict, db):
    callback = update.get("callback", {})
    callback_id = callback.get("callback_id")
    payload = callback.get("payload") or ""
    user = callback.get("user") or {}
    user_id = user.get("user_id")

    if not callback_id or not user_id:
        return

    await db.get_or_create_user(user_id)

    if payload == "menu:main":
        await start_h.handle_menu(client, user_id, None)
    elif payload == "menu:upload":
        await upload_h.handle_upload_start(client, user_id, None, db)
    elif payload == "menu:styles":
        await styles_h.show_styles_menu(client, user_id, None, callback_id=callback_id)
    elif payload == "menu:tokens":
        await client.answer_callback(callback_id, text="…")
        await menu_h.handle_tokens(client, user_id, None, db)
    elif payload == "menu:clean":
        await client.answer_callback(callback_id, text="🗑 Очищаем…")
        await clean_h.handle_clean(client, user_id, None, db)
    elif payload == "menu:help":
        await client.answer_callback(callback_id, text="❓")
        await start_h.handle_help(client, user_id, None)
    elif payload == "menu:couple":
        await client.answer_callback(callback_id, text="👫")
        await couple_h.couple_start(client, user_id, None)
    elif payload == "menu:custom":
        await client.answer_callback(callback_id, text="✍️")
        await custom_h.custom_start(client, user_id, None, db)
    elif payload == "menu:video":
        await client.answer_callback(callback_id, text="🎬")
        await video_h.video_start(client, user_id, None)
    elif payload == "menu:buy":
        await client.answer_callback(callback_id, text="💳")
        await client.send_message(user_id=user_id,
                                   text="Выберите стиль, затем модель — и нажмите «Купить».",
                                   attachments=main_menu_keyboard())
    elif payload.startswith("select_style_"):
        await styles_h.handle_style_selected(client, user_id, None, callback_id, payload, db)
    elif payload.startswith("select_model_"):
        await styles_h.handle_model_selected(client, user_id, None, callback_id, payload, db)
    elif payload == "use_token":
        await client.answer_callback(callback_id, text="💎 Генерируем…")
        # Быстрый запуск генерации через жетоны (упрощённо)
        data = fsm.get(user_id)
        style = data.get("selected_style")
        model = data.get("selected_model", "gemini")
        if not style:
            await client.answer_callback(callback_id, text="❌ Сначала выберите стиль.")
            return
        # Здесь в идеале переиспользовать generate_photo_with_tokens из styles.py,
        # но для MVP упростим через прямую генерацию:
        await styles_h.generate_photo_with_tokens(client, user_id, None, db, style, model)
    elif payload == "buy_generation":
        await client.answer_callback(callback_id, text="💳 Создаём платёж…")
        data = fsm.get(user_id)
        style = data.get("selected_style")
        model = data.get("selected_model", "gemini")
        if not style:
            await client.answer_callback(callback_id, text="❌ Сначала выберите стиль.")
            return
        await payment_h.create_single_payment(client, user_id=user_id, chat_id=None,
                                                db=db, style_key=style, model=model)
    elif payload == "buy_tokens":
        await client.answer_callback(callback_id, text="💳 Создаём платёж…")
        await payment_h.create_tokens_payment(client, user_id=user_id, chat_id=None, db=db)
    elif payload == "upload:done":
        await upload_h.handle_upload_done(client, user_id, None, callback_id, db)
    elif payload == "upload:cancel":
        await upload_h.handle_upload_cancel(client, user_id, None, callback_id)
    elif payload.startswith("couple_style_"):
        await couple_h.handle_style_callback(client, user_id, None, callback_id, payload, db)
    elif payload == "couple_pay_tokens":
        await couple_h.pay_with_tokens(client, user_id, None, callback_id, db)
    elif payload == "couple_pay_money":
        await couple_h.pay_with_money(client, user_id, None, callback_id, db)
    elif payload == "couple_cancel":
        await couple_h.cancel(client, user_id, None, callback_id)
    elif payload == "video_done":
        await video_h.handle_done(client, user_id, None, callback_id)
    elif payload.startswith("video_model_"):
        await video_h.handle_model_callback(client, user_id, None, callback_id, payload, db)
    elif payload == "video_pay_tokens":
        await video_h.pay_with_tokens(client, user_id, None, callback_id, db)
    elif payload == "video_pay_money":
        await video_h.pay_with_money(client, user_id, None, callback_id, db)
    elif payload == "video_cancel":
        await video_h.cancel(client, user_id, None, callback_id)
    elif payload == "custom_pay_tokens":
        await custom_h.pay_tokens(client, user_id, None, callback_id, db)
    elif payload == "custom_pay_money":
        await custom_h.pay_with_money(client, user_id, None, callback_id, db)
    elif payload == "custom_cancel":
        fsm.clear(user_id)
        await client.answer_callback(callback_id, text="Отменено.",
                                      attachments=main_menu_keyboard())
    else:
        logger.warning(f"Неизвестный payload: {payload}")
        await client.answer_callback(callback_id, text=f"Неизвестное действие: {payload}")


async def handle_update(client: MaxClient, update: dict, db):
    utype = update.get("update_type")
    try:
        if utype == "message_created":
            await handle_message(client, update, db)
        elif utype == "message_callback":
            await handle_callback(client, update, db)
        elif utype == "bot_started":
            sender = update.get("user") or {}
            user_id = sender.get("user_id")
            if user_id:
                await db.get_or_create_user(user_id, first_name=sender.get("first_name", ""))
                await start_h.handle_start(client, user_id, None, db,
                                            first_name=sender.get("first_name", ""))
    except Exception as e:
        logger.error(f"Ошибка обработки update {utype}: {e}", exc_info=True)


async def clean_old_files_job():
    """Удаляет файлы старше 7 дней из UPLOAD_DIR и OUTPUT_DIR."""
    from datetime import datetime, timedelta
    now = datetime.now()
    deleted = 0
    for base in (Config.UPLOAD_DIR, Config.OUTPUT_DIR):
        if not os.path.exists(base):
            continue
        for root, _, files in os.walk(base):
            for f in files:
                p = os.path.join(root, f)
                try:
                    if now - datetime.fromtimestamp(os.path.getmtime(p)) > timedelta(days=7):
                        os.remove(p)
                        deleted += 1
                except Exception:
                    pass
    if deleted:
        logger.info(f"🗑️ Удалено {deleted} старых файлов")


async def scheduler_loop():
    while True:
        # ждём до 03:00 следующего дня
        from datetime import datetime, timedelta
        now = datetime.now()
        target = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        wait = (target - now).total_seconds()
        logger.info(f"⏰ Следующая очистка через {wait/3600:.1f} ч")
        await asyncio.sleep(wait)
        try:
            await clean_old_files_job()
        except Exception as e:
            logger.error(f"Ошибка очистки: {e}")


async def main():
    Config.validate()
    Config.ensure_dirs()
    logger.info("✅ Конфигурация валидна")

    db = await get_db()
    logger.info("✅ БД подключена")

    ssl_ctx = build_ssl_context()
    client = MaxClient(token=Config.MAX_BOT_TOKEN, ssl_context=ssl_ctx)

    try:
        me = await client.get_me()
        logger.info(f"🤖 Бот: @{me.get('username')} (id={me.get('user_id')})")
    except Exception as e:
        logger.error(f"Не удалось получить данные бота: {e}")
        await client.close()
        await close_db()
        return

    # Веб-сервер (для ЮKassa-вебхука всегда, для MAX — если webhook)
    from webhook_server import start_webhook_server
    runner = await start_webhook_server(client, db)

    sched_task = asyncio.create_task(scheduler_loop())

    try:
        marker = None
        while True:
            try:
                data = await client.get_updates(
                    timeout=Config.MAX_POLL_TIMEOUT,
                    marker=marker,
                    types=["message_created", "message_callback", "bot_started"],
                )
            except Exception as e:
                logger.error(f"Ошибка get_updates: {e}")
                await asyncio.sleep(3)
                continue

            updates = data.get("updates", [])
            new_marker = data.get("marker")
            if new_marker is not None:
                marker = new_marker

            for upd in updates:
                asyncio.create_task(handle_update(client, upd, db))
    except asyncio.CancelledError:
        logger.info("Получен сигнал остановки")
    finally:
        sched_task.cancel()
        await runner.cleanup()
        await client.close()
        await close_db()
        logger.info("✅ Всё закрыто")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановлено вручную")