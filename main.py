"""Точка входа: FastAPI + aiogram webhook + health-check + фоновый таймаут-воркер."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ErrorEvent, Update
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, Request, Response

from app.ban import BanMiddleware
from app.battle_service import BattleService
from app.boss_repo import BossRepo
from app.cards import CARDS, card_rows
from app.commands import ADMIN_COMMANDS, COMMANDS
from app.config import settings
from app import event
from app.db import Database
from app.dungeon_hero import DungeonHeroRepo
from app.dungeon_hub import DungeonHub
from app.dungeon_repo import DungeonBossRepo
from app.handlers import router
from app.market_repo import MarketRepo
from app.quest_repo import QuestRepo
from app.shop import ShopRepo
from app import stocks_alerts
from app.stocks_repo import StocksRepo
from app.team_service import TeamBattleService
from app.webapp import router as webapp_router

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
        BotCommandScopeChat,
        BotCommandScopeDefault,
    )

    for scope in (
        BotCommandScopeDefault(),
        BotCommandScopeAllPrivateChats(),
        BotCommandScopeAllGroupChats(),
    ):
        await bot.set_my_commands(COMMANDS, scope=scope)

    # Админу — отдельное меню, где видно /admin. Остальным он не светится.
    for admin_id in settings.admin_ids:
        with contextlib.suppress(Exception):
            await bot.set_my_commands(
                ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id)
            )
            log.info("Админское меню выставлено для %s", admin_id)

    log.info("Меню команд обновлено: %d шт.", len(COMMANDS))


async def _safe_tick(name: str, factory) -> Any:
    """Один шаг фонового сервиса: ошибку пишем в лог, но цикл не роняем.

    Раньше ошибки молча глотались — из-за этого биржа могла «зависнуть»,
    а в логах не было ни строчки.
    """
    try:
        return await asyncio.wait_for(factory(), timeout=25)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        log.exception("Тикер: %s не прошли", name)
        return None


async def _ticker(
    bot: Bot,
    db: Database,
    service: BattleService,
    team: TeamBattleService,
    stocks: StocksRepo,
) -> None:
    while True:
        try:
            await asyncio.sleep(15)
            await _safe_tick("бои", service.tick)
            await _safe_tick("командные бои", team.tick)
            # сообщаем в чат, когда счастливая минута закончилась
            await _safe_tick("счастливая минута", lambda: event.tick(bot, db))
            # Живой курс биржи: шаг каждые 15 секунд + оповещения о росте.
            alerts = await _safe_tick("биржа", stocks.tick)
            if alerts:
                with contextlib.suppress(Exception):
                    await stocks_alerts.broadcast(bot, db, alerts)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Тикер: неожиданная ошибка, продолжаю")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = Database(settings.database_url)
    await db.connect()
    await db.init_schema()
    await db.upsert_cards(card_rows())
    # Убираем из базы карты, которых уже нет в каталоге: иначе их строки
    # у игроков ломают просмотр профиля (get_card кидает KeyError).
    # Чистим только то, чего нет НИ В ОДНОЙ коллекции: иначе «7Д»
    # заливалась и тут же удалялась при каждом старте.
    from app.cards_d import CARDS_D

    await db.purge_missing_cards(
        [card.card_id for card in CARDS] + [card.card_id for card in CARDS_D]
    )

    market = MarketRepo(db)
    await market.seed_items()

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    # Бан: забаненный не доходит ни до одного обработчика.
    dp.message.middleware(BanMiddleware())
    dp.callback_query.middleware(BanMiddleware())

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        log.exception("Необработанная ошибка апдейта", exc_info=event.exception)
        # Если упал обработчик кнопки, Telegram будет крутить спиннер вечно.
        # Отвечаем принудительно, чтобы игрок увидел хоть что-то.
        query = event.update.callback_query
        if query is not None:
            with contextlib.suppress(Exception):
                await query.answer("⚠️ Ошибка, попробуй ещё раз", show_alert=True)
        return True

    dp.include_router(router)
    service = BattleService(bot, db, market)
    team = TeamBattleService(bot, db, market)
    shop = ShopRepo(db, market)
    stocks = StocksRepo(db)
    await stocks.seed()
    boss_repo = BossRepo(db)
    dungeon_boss = DungeonBossRepo(db)
    hub = DungeonHub()
    hero = DungeonHeroRepo(db)
    quest_repo = QuestRepo(db)

    # мини-аппка магазина читает это из app.state
    app.state.settings = settings
    app.state.db = db
    app.state.market = market
    app.state.shop = shop
    app.state.stocks = stocks
    app.state.boss = boss_repo
    app.state.dungeon = dungeon_boss
    app.state.hub = hub
    app.state.hero = hero
    app.state.quests = quest_repo
    runtime.update(
        db=db,
        bot=bot,
        dp=dp,
        service=service,
        market=market,
        team=team,
        stocks=stocks,
        boss_repo=boss_repo,
    )

    # Telegram иногда не отвечает минутами. Раньше из-за этого падал ВЕСЬ
    # сервис и деплой откатывался: мини-аппки не обновлялись. Теперь просто
    # поднимаемся без меню команд, а / и аппки работают как обычно.
    me = None
    for attempt in range(1, 6):
        try:
            me = await bot.get_me()
            break
        except Exception as error:  # noqa: BLE001
            log.warning("Telegram не ответил (попытка %d/5): %s", attempt, error)
            await asyncio.sleep(4)
    if me is not None:
        log.info("Бот: @%s (%s)", me.username, me.id)

    try:
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
    except Exception:  # noqa: BLE001
        log.exception("Не настроил Telegram — сервис всё равно поднимается")

    base = (os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
    if base:
        from aiogram.types import MenuButtonWebApp, WebAppInfo

        with contextlib.suppress(Exception):
            # Кнопка слева от поля ввода в личке. Ведёт в главное приложение,
            # а не сразу в магазин: оттуда уже все разделы.
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="Приложение", web_app=WebAppInfo(url=f"{base}/hub")
                )
            )
            log.info("Кнопка меню: Приложение -> %s/hub", base)

    task = asyncio.create_task(_ticker(bot, db, service, team, stocks))
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


app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.middleware("http")
async def no_store(request: Request, call_next):
    """Мини-аппки не кэшируем.

    Telegram и WebView держат страницы и ответы API в кэше — из-за этого
    игроки видели старые цифры (например, уровень 1 вместо 40) даже после
    исправления. Теперь браузер обязан спрашивать сервер заново.
    """
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/api/") or path in (
        "/",
        "/app",
        "/market",
        "/buyer",
        "/upgrader",
        "/hub",
        "/casino_app",
        "/roulette_table",
        "/yugi",
        "/case_app",
        "/stocks",
    ):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


# Роуты мини-аппок подключаем сразу при импорте, а не в lifespan: иначе они
# добавляются в уже работающий роутер на каждом старте.
app.include_router(webapp_router)


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
    return {
        "ok": True,
        "service": "severo-yug-bot",
        "db": alive,
        # Render подставляет сюда хеш задеплоенного коммита: по нему видно,
        # что на сервере именно тот код, который лежит в репозитории
        "version": (os.getenv("RENDER_GIT_COMMIT") or "dev")[:7],
        # сколько админов прописано в ADMIN_IDS — видно, что бот их прочитал
        "admins": len(settings.admin_ids),
    }


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
            boss_repo=runtime["boss_repo"],
        )
    except Exception:  # noqa: BLE001 - всегда отвечаем 200, иначе Telegram будет ретраить
        log.exception("Ошибка обработки апдейта")
    return Response(status_code=200)
