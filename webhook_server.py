import asyncio
import logging
import os

from aiohttp import web

from config import Config
from max_client import MaxClient

logger = logging.getLogger(__name__)


async def health_handler(request):
    return web.Response(text="OK")


async def yookassa_webhook_handler(request):
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="Invalid JSON")

    client: MaxClient = request.app["client"]
    db = request.app["db"]
    from handlers.payment import process_yookassa_webhook
    asyncio.create_task(process_yookassa_webhook(data, client, db))
    return web.Response(text="OK")


async def start_webhook_server(client: MaxClient, db):
    app = web.Application()
    app["client"] = client
    app["db"] = db
    app.router.add_get("/health", health_handler)
    app.router.add_post("/yookassa-webhook", yookassa_webhook_handler)

    port = Config.MAX_WEBHOOK_PORT
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"🌐 Веб-сервер запущен на порту {port}")
    return runner