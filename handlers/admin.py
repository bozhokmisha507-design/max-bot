import asyncio
import logging

from config import Config
from max_client import MaxClient
from fsm import fsm

logger = logging.getLogger(__name__)

STATE_ADD_USER = "admin:add_user"
STATE_ADD_AMOUNT = "admin:add_amount"


async def is_admin(user_id: int) -> bool:
    return user_id in Config.ADMIN_IDS


async def add_tokens_start(client: MaxClient, user_id: int, chat_id: int | None):
    if not await is_admin(user_id):
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                  text="⛔ Нет прав.")
        return
    fsm.set_state(user_id, STATE_ADD_USER)
    await client.send_message(user_id=user_id, chat_id=chat_id,
                              text="🔹 Введите user_id, которому начислить жетоны:")


async def add_tokens_user(client: MaxClient, user_id: int, chat_id: int | None, text: str):
    if not await is_admin(user_id):
        return
    try:
        target = int(text.strip())
    except ValueError:
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                  text="❌ Введите число.")
        return
    fsm.update(user_id, admin_target=target)
    fsm.set_state(user_id, STATE_ADD_AMOUNT)
    await client.send_message(user_id=user_id, chat_id=chat_id,
                              text="🔹 Введите количество жетонов:")


async def add_tokens_amount(client: MaxClient, user_id: int, chat_id: int | None,
                             text: str, db):
    if not await is_admin(user_id):
        return
    try:
        amount = int(text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                  text="❌ Введите положительное число.")
        return

    target = fsm.get(user_id).get("admin_target")
    if not target:
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                  text="❌ Потерян target.")
        fsm.clear(user_id)
        return

    await db.add_tokens(target, amount)
    await client.send_message(user_id=user_id, chat_id=chat_id,
                              text=f"✅ Начислено {amount} жетонов user {target}.")

    try:
        await client.send_message(user_id=target,
                                  text=f"🎁 Вам начислено {amount} жетонов!")
    except Exception as e:
        logger.warning(f"Не удалось уведомить {target}: {e}")

    fsm.clear(user_id)


async def broadcast(client: MaxClient, user_id: int, chat_id: int | None,
                    args: str, db):
    if not await is_admin(user_id):
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                  text="⛔ Нет прав.")
        return
    if not args.strip():
        await client.send_message(user_id=user_id, chat_id=chat_id,
                                  text="Использование: /broadcast текст сообщения")
        return

    text = args.strip()
    await client.send_message(user_id=user_id, chat_id=chat_id,
                              text=f"⏳ Рассылка: _{text}_")

    user_ids = await db.get_all_user_ids()
    ok = fail = 0
    for uid in user_ids:
        try:
            await client.send_message(user_id=uid, text=text)
            ok += 1
            await asyncio.sleep(0.05)  # 20 rps, с запасом
        except Exception as e:
            fail += 1
            logger.warning(f"Не отправлено {uid}: {e}")

    await client.send_message(user_id=user_id, chat_id=chat_id,
                              text=f"✅ Отправлено: {ok}\n❌ Ошибок: {fail}")