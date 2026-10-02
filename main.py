"""Точка входа: FastAPI + aiogram webhook + health-check + фоновый таймаут-воркер."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ErrorEvent, Update
from fastapi import FastAPI, Request, Response

from app.battle_service import BattleService
from app.cards import CARDS, card_rows
from app.config import settings
from app.db import Database
from app.handlers import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("severo-yug")

runtime: dict[str, Any] = {}


async def _ticker(service: BattleService) -> None:
    while True:
        await asyncio.sleep(15)
        with contextlib.suppress(Exception):
            await service.tick()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = Database(settings.database_url)
    await db.connect()
    await db.init_schema()
    await db.upsert_cards(card_rows())

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        log.exception("Необработанная ошибка апдейта", exc_info=event.exception)
        return True

    dp.include_router(router)
    service = BattleService(bot, db)
    runtime.update(db=db, bot=bot, dp=dp, service=service)

    url = settings.webhook_url()
    if url:
        await bot.set_webhook(
            url=url,
            secret_token=settings.webhook_token,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=True,
        )
        log.info("Webhook установлен: %s", url)
    else:
        log.warning("PUBLIC_URL/RENDER_EXTERNAL_URL не задан — вебхук не установлен")

    task = asyncio.create_task(_ticker(service))
    log.info("Бот запущен: %d карт", len(CARDS))
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await bot.session.close()
        await db.close()


app = FastAPI(title="severo-yug-bot", lifespan=lifespan)


@app.get("/")
async def health() -> dict[str, Any]:
    db_ready = runtime.get("db") is not None
    return {"ok": True, "service": "severo-yug-bot", "db": db_ready}


@app.get("/healthz")
async def healthz() -> Response:
    return Response(status_code=200, content="ok")


@app.post(settings.webhook_path)
async def telegram_webhook(request: Request) -> Response:
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != settings.webhook_token:
        return Response(status_code=403)

    bot = runtime.get("bot")
    dp = runtime.get("dp")
    if bot is None or dp is None:
        return Response(status_code=503)

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return Response(status_code=400)

    try:
        update = Update.model_validate(payload, context={"bot": bot})
        await dp.feed_update(
            bot, update, db=runtime["db"], service=runtime["service"]
        )
    except Exception:  # noqa: BLE001 - всегда отвечаем 200, иначе Telegram будет ретраить
        log.exception("Ошибка обработки апдейта")
    return Response(status_code=200)
