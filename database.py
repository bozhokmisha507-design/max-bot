import json
import logging
from typing import Optional, List, Dict, Any

import asyncpg

from config import Config

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    gender TEXT,
    tokens INTEGER DEFAULT 0,
    selected_style TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS photos (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
    file_id TEXT,
    file_path TEXT NOT NULL,
    type TEXT DEFAULT 'input',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    label TEXT UNIQUE NOT NULL,
    user_id BIGINT,
    amount NUMERIC(10, 2) NOT NULL,
    status TEXT DEFAULT 'pending',
    data JSONB,
    payment_id TEXT,
    processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_photos_user_type ON photos(user_id, type);
CREATE INDEX IF NOT EXISTS idx_orders_label ON orders(label);
"""


class Database:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        if not Config.DATABASE_URL:
            raise ValueError("MAX_DATABASE_URL не задан")
        self.pool = await asyncpg.create_pool(Config.DATABASE_URL, min_size=1, max_size=10)
        async with self.pool.acquire() as conn:
            await conn.execute(SCHEMA)
        logger.info("БД подключена и схема проверена")

    async def close(self):
        if self.pool:
            await self.pool.close()

    # ---------- Пользователи ----------
    async def get_or_create_user(self, user_id: int, username: str = "", first_name: str = ""):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO users (user_id, username, first_name)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (user_id) DO UPDATE
                   SET username = EXCLUDED.username, first_name = EXCLUDED.first_name""",
                user_id, username, first_name,
            )

    async def get_user_gender(self, user_id: int) -> Optional[str]:
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT gender FROM users WHERE user_id = $1", user_id)

    async def set_user_gender(self, user_id: int, gender: str):
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE users SET gender = $1 WHERE user_id = $2", gender, user_id)

    async def get_user_tokens(self, user_id: int) -> int:
        async with self.pool.acquire() as conn:
            return (await conn.fetchval("SELECT tokens FROM users WHERE user_id = $1", user_id)) or 0

    async def add_tokens(self, user_id: int, amount: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET tokens = COALESCE(tokens, 0) + $1 WHERE user_id = $2",
                amount, user_id,
            )

    async def use_tokens(self, user_id: int, amount: int) -> bool:
        async with self.pool.acquire() as conn:
            res = await conn.execute(
                "UPDATE users SET tokens = tokens - $1 WHERE user_id = $2 AND tokens >= $1",
                amount, user_id,
            )
            return res.endswith("1")

    async def set_user_selected_style(self, user_id: int, style_key: str):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET selected_style = $1 WHERE user_id = $2", style_key, user_id,
            )

    async def get_user_selected_style(self, user_id: int) -> Optional[str]:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT selected_style FROM users WHERE user_id = $1", user_id,
            )

    # ---------- Фото ----------
    async def add_photo(self, user_id: int, file_id: str, file_path: str, ptype: str = "input"):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO photos (user_id, file_id, file_path, type) VALUES ($1, $2, $3, $4)",
                user_id, file_id, file_path, ptype,
            )

    async def get_user_photos(self, user_id: int, ptype: str = "input") -> List[str]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT file_path FROM photos WHERE user_id = $1 AND type = $2 ORDER BY id",
                user_id, ptype,
            )
            return [r["file_path"] for r in rows]

    async def get_user_photo_count(self, user_id: int) -> int:
        async with self.pool.acquire() as conn:
            return (await conn.fetchval(
                "SELECT COUNT(*) FROM photos WHERE user_id = $1 AND type = 'input'", user_id
            )) or 0

    async def clear_user_photos(self, user_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM photos WHERE user_id = $1 AND type = 'input'", user_id,
            )

    # ---------- Заказы ----------
    async def create_order(self, user_id: int, label: str, amount: float,
                           data: Optional[dict] = None):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO orders (user_id, label, amount, data)
                   VALUES ($1, $2, $3, $4::jsonb)""",
                user_id, label, amount, json.dumps(data or {}, ensure_ascii=False),
            )

    async def update_order_payment_id(self, label: str, payment_id: str):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE orders SET payment_id = $1 WHERE label = $2", payment_id, label,
            )

    async def get_order_data(self, label: str) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT data FROM orders WHERE label = $1", label)
            if row and row["data"]:
                return json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
            return None

    async def is_order_processed(self, label: str) -> bool:
        async with self.pool.acquire() as conn:
            return bool(await conn.fetchval(
                "SELECT processed FROM orders WHERE label = $1", label,
            ))

    async def mark_order_processed(self, label: str):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE orders SET processed = TRUE, status = 'succeeded' WHERE label = $1", label,
            )

    async def get_all_user_ids(self) -> List[int]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT user_id FROM users")
            return [r["user_id"] for r in rows]


_db_instance: Optional[Database] = None


async def get_db() -> Database:
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
        await _db_instance.connect()
    return _db_instance


async def close_db():
    global _db_instance
    if _db_instance:
        await _db_instance.close()
        _db_instance = None