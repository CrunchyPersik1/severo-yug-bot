"""Точка входа: FastAPI + aiogram webhook + health-check + фоновый таймаут-воркер."""

from __future__ import annotations

import asyncio
import contextlib
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
from app.commands import COMMANDS
from app.config import settings
from app.db import Database
from app.handlers import router
from app.market_repo import MarketRepo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("severo-yug")

runtime: dict[str, Any] = {}


async def setup_commands(bot: Bot) -> None:
    """Меню команд при вводе «/» — и в личке, и в группах."""
    from aiogram.types import (
        BotCommandScopeAllGroupChats,
        BotCommandScopeAllPrivateChats,
        BotCommandScopeDefault,
    )

    for scope in (
        BotCommandScopeDefault(),
        BotCommandScopeAllPrivateChats(),
        BotCommandScopeAllGroupChats(),
    ):
        await bot.set_my_commands(COMMANDS, scope=scope)
    log.info("Меню команд обновлено: %d шт.", len(COMMANDS))


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

    market = MarketRepo(db)
    await market.seed_items()

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        log.exception("Необработанная ошибка апдейта", exc_info=event.exception)
        return True

    dp.include_router(router)
    service = BattleService(bot, db, market)
    runtime.update(db=db, bot=bot, dp=dp, service=service, market=market)

    me = await bot.get_me()
    log.info("Бот: @%s (%s)", me.username, me.id)

    await setup_commands(bot)

    url = settings.webhook_url()
    if url:
        # Ставим вебхук только если он изменился: иначе каждый холодный старт
        # после сна Render стирал бы очередь апдейтов и терял сообщения.
        info = await bot.get_webhook_info()
        if info.url != url:
            await bot.set_webhook(
                url=url,
                secret_token=settings.webhook_token,
                allowed_updates=dp.resolve_used_update_types(),
            )
            log.info("Webhook установлен: %s", url)
        else:
            log.info("Webhook уже настроен: %s", url)
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
    """Health-check и точка для внешнего пингера.

    Всегда отвечает 200 (чтобы Render не перезапускал сервис), но реально
    дёргает БД — так Supabase не считает проект неактивным и не усыпляет его.
    """
    database = runtime.get("db")
    alive = False
    if database is not None:
        try:
            alive = await database.ping()
        except Exception:  # noqa: BLE001
            log.warning("Health-check: БД недоступна", exc_info=True)
    return {"ok": True, "service": "severo-yug-bot", "db": alive}


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
            bot,
            update,
            db=runtime["db"],
            service=runtime["service"],
            market=runtime["market"],
        )
    except Exception:  # noqa: BLE001 - всегда отвечаем 200, иначе Telegram будет ретраить
        log.exception("Ошибка обработки апдейта")
    return Response(status_code=200)
