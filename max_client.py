import asyncio
import logging
import os
import ssl
import time
from typing import Any, Dict, List, Optional

import aiohttp

from config import Config

logger = logging.getLogger(__name__)


class MaxApiError(Exception):
    def __init__(self, status: int, data: Any):
        super().__init__(f"MAX API error {status}: {data}")
        self.status = status
        self.data = data


class RateLimiter:
    """Ограничивает запросы к MAX API (30 rps максимум)."""
    def __init__(self, rate: int = 25):
        self._interval = 1.0 / rate
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            wait = self._last + self._interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()


class MaxClient:
    def __init__(self, token: str, base_url: str = Config.MAX_API_BASE_URL,
                 ssl_context: Optional[ssl.SSLContext] = None):
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._ssl = ssl_context
        self._session: Optional[aiohttp.ClientSession] = None
        self._limiter = RateLimiter(rate=25)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = None
            if self._ssl:
                connector = aiohttp.TCPConnector(ssl=self._ssl)
            self._session = aiohttp.ClientSession(
                headers={"Authorization": self._token},
                connector=connector,
            )
        return self._session

    async def request(self, method: str, path: str, *,
                      params: Optional[dict] = None,
                      json: Optional[dict] = None,
                      retries: int = 3) -> Any:
        for attempt in range(retries):
            await self._limiter.acquire()
            session = await self._get_session()
            url = f"{self._base_url}{path}"
            try:
                async with session.request(method, url, params=params, json=json) as resp:
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        text = await resp.text()
                        raise MaxApiError(resp.status, text)

                    if resp.status == 429 and attempt < retries - 1:
                        logger.warning("429 Too Many Requests, ждём 2 сек")
                        await asyncio.sleep(2 * (attempt + 1))
                        continue

                    if resp.status >= 400:
                        raise MaxApiError(resp.status, data)
                    return data
            except aiohttp.ClientError as e:
                if attempt < retries - 1:
                    logger.warning(f"Сетевая ошибка, повтор {attempt+1}: {e}")
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                raise

    # ---------- Обновления ----------
    async def get_updates(self, timeout: int = 30,
                          marker: Optional[int] = None,
                          types: Optional[List[str]] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"timeout": timeout}
        if marker is not None:
            params["marker"] = marker
        if types:
            params["types"] = ",".join(types)
        return await self.request("GET", "/updates", params=params)

    # ---------- Сообщения ----------
    async def send_message(self, *,
                           chat_id: Optional[int] = None,
                           user_id: Optional[int] = None,
                           text: str,
                           attachments: Optional[list] = None) -> Dict[str, Any]:
        if chat_id is None and user_id is None:
            raise ValueError("Нужно указать chat_id или user_id")

        params: Dict[str, Any] = {}
        if chat_id is not None:
            params["chat_id"] = chat_id
        if user_id is not None:
            params["user_id"] = user_id

        body: Dict[str, Any] = {"text": text}
        if attachments:
            body["attachments"] = attachments

        return await self.request("POST", "/messages", params=params, json=body)

    async def answer_callback(self, callback_id: str, *,
                              text: Optional[str] = None,
                              attachments: Optional[list] = None,
                              notification: Optional[str] = None) -> Dict[str, Any]:
        params = {"callback_id": callback_id}
        body: Dict[str, Any] = {}
        if text is not None:
            body["text"] = text
        if attachments is not None:
            body["attachments"] = attachments
        if notification is not None:
            body["notification"] = notification
        return await self.request("POST", "/answers", params=params, json=body)

    # ---------- Медиа ----------
    async def _upload(self, file_path: str, media_type: str) -> str:
        """Загружает файл и возвращает attachment token."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(file_path)

        info = await self.request("POST", "/uploads", params={"type": media_type})
        upload_url = info.get("url")
        if not upload_url:
            raise MaxApiError(0, f"Нет upload url в ответе: {info}")

        session = await self._get_session()
        with open(file_path, "rb") as f:
            form = aiohttp.FormData()
            form.add_field("data", f, filename=os.path.basename(file_path))
            async with session.post(upload_url, data=form) as resp:
                data = await resp.json(content_type=None)
                if resp.status != 200:
                    raise MaxApiError(resp.status, data)

        # Структура ответа может отличаться для image/video — обрабатываем оба случая
        if media_type == "image":
            photos = data.get("photos") or {}
            if photos:
                first = next(iter(photos.values()))
                return first.get("token") or first.get("token".upper())
        token = data.get("token") or (data.get("video") or {}).get("token")
        if not token:
            raise MaxApiError(0, f"Не удалось получить token из ответа: {data}")
        return token

    async def send_photo(self, *,
                         chat_id: Optional[int] = None,
                         user_id: Optional[int] = None,
                         file_path: str,
                         text: str = "",
                         attachments: Optional[list] = None) -> Dict[str, Any]:
        token = await self._upload(file_path, "image")
        all_att = [{"type": "image", "payload": {"token": token}}]
        if attachments:
            all_att.extend(attachments)
        return await self.send_message(
            chat_id=chat_id, user_id=user_id, text=text, attachments=all_att,
        )

    async def send_video(self, *,
                         chat_id: Optional[int] = None,
                         user_id: Optional[int] = None,
                         file_path: str,
                         text: str = "") -> Dict[str, Any]:
        token = await self._upload(file_path, "video")
        all_att = [{"type": "video", "payload": {"token": token}}]
        return await self.send_message(
            chat_id=chat_id, user_id=user_id, text=text, attachments=all_att,
        )

    async def download_attachment(self, url: str, save_path: str) -> str:
        """Скачивает вложение по URL (например, фото, отправленное пользователем)."""
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        session = await self._get_session()
        async with session.get(url) as resp:
            if resp.status != 200:
                raise MaxApiError(resp.status, f"Не удалось скачать файл: {url}")
            with open(save_path, "wb") as f:
                f.write(await resp.read())
        return save_path

    async def get_me(self) -> Dict[str, Any]:
        return await self.request("GET", "/me")

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


def build_ssl_context() -> Optional[ssl.SSLContext]:
    if not Config.MAX_SSL_VERIFY:
        logger.warning("SSL-проверка отключена (только для отладки!)")
        return None

    cert_path = "certs/russian_trusted_root_ca.pem"
    try:
        ctx = ssl.create_default_context(cafile=cert_path)
        logger.info(f"SSL-контекст создан с сертификатом: {cert_path}")
        return ctx
    except FileNotFoundError:
        logger.warning(
            f"Сертификат {cert_path} не найден. Используется системное хранилище."
        )
        return ssl.create_default_context()