"""Хэндлеры aiogram: выпадение карт, коллекция, лидерборд и PvP."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandStart, Filter
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message

from . import (
    admin_actions,
    boss,
    buyer,
    casino,
    clicker,
    dice_casino,
    event,
    kopilka,
    profiles,
    promo,
    referrals,
    render,
    themes,
    team_battle,
)
from .battle import ability_targets
from .battle_service import BattleError, BattleService
from .casino_repo import CasinoError, CasinoRepo
from .promo import PromoError
from .referrals import ReferralError
from .team_service import TeamBattleError, TeamBattleService
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from .config import settings
from .cards import CARDS, CARDS_BY_ID, cards_sorted_for_user, get_card, image_url
from .cases import OPEN_PER_DAY, roll_case_card
from .db import Database
from .gacha import DROPS_PER_DAY, day_key, next_reset, roll_card
from .roulette import (
    PRIZE_CASE,
    PRIZE_POINTS,
    SPINS_PER_DAY,
    next_roulette_reset,
    roll_prize,
    roulette_day_key,
)
from .items import SLOT_ICONS
from .market import UPGRADE_PRICE, effective_stats, parse_handle, sum_bonus
from .boss_repo import BossError, BossRepo
from .market_repo import MarketError, MarketRepo, item_of

MARKET_PAGE_SIZE = 6

log = logging.getLogger(__name__)

router = Router(name="severo-yug")

_SPACING = re.compile(r"[\s\-_.,!?]+")


def normalize(text: str) -> str:
    return _SPACING.sub("", text.strip().lower().replace("ё", "е"))


class NormalizedText(Filter):
    """Сравнение текста без учёта регистра, пробелов и дефисов."""

    def __init__(self, *variants: str) -> None:
        self.variants = {normalize(variant) for variant in variants}

    async def __call__(self, message: Message) -> bool:
        if not message.text:
            return False
        return normalize(message.text) in self.variants


class UpdateWord(Filter):
    """Слово-рубильник: «ОБНОВЛЕНИЕ» в любом регистре и с пробелами вокруг."""

    async def __call__(self, message: Message) -> bool:
        return bool(message.text) and message.text.strip().upper() == "ОБНОВЛЕНИЕ"


def _humanize(delta_seconds: float) -> str:
    total = max(0, int(delta_seconds))
    hours, remainder = divmod(total, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours} ч {minutes} мин"
    return f"{minutes} мин"


# --------------------------------------------------------------------------- #
# Команды
# --------------------------------------------------------------------------- #


async def _bot_username(bot: Bot) -> str:
    """Имя бота для справки. get_me кешируется внутри aiogram."""
    me = getattr(bot, "_me", None)
    if me is None:
        try:
            me = await bot.get_me()
        except Exception:  # noqa: BLE001 - справка должна работать всегда
            return "бот"
    return getattr(me, "username", None) or "бот"


@router.message(Command("help"))
async def cmd_help(message: Message, bot: Bot) -> None:
    await message.answer(render.render_help(await _bot_username(bot)))


_SEEN_CHATS: set[int] = set()


@router.message.outer_middleware()
@router.callback_query.outer_middleware()
async def levelup_notify(handler, event, data):
    """После любого действия выдаёт награды за новые уровни и сообщает о них."""
    result = await handler(event, data)
    db = data.get("db")
    bot = data.get("bot")
    user = getattr(event, "from_user", None)
    if db is None or bot is None or user is None:
        return result
    try:
        summary = await db.apply_pending_levels(user.id)
    except Exception:  # noqa: BLE001 - игра важнее награды
        log.exception("Не смог выдать награды за уровень")
        return result
    if not summary.get("levels"):
        return result
    text = render.render_levelup(summary)
    if not text:
        return result
    # Уровень — личное дело: шлём игроку в личку, а не в общую группу.
    try:
        await bot.send_message(user.id, text)
    except Exception:  # noqa: BLE001 - не написать в лс (не начинал бота)
        chat = getattr(event, "chat", None)
        if chat is None:
            chat = getattr(getattr(event, "message", None), "chat", None)
        if chat is not None:
            with contextlib.suppress(Exception):
                await bot.send_message(chat.id, text)
    return result


@router.message.outer_middleware()
async def track_chat(handler, event, data):
    """Запоминает группы, где есть бот, — чтобы было куда рассылать."""
    chat = getattr(event, "chat", None)
    if chat is not None and chat.type in ("group", "supergroup"):
        if chat.id not in _SEEN_CHATS:
            db = data.get("db")
            if db is not None:
                try:
                    await db.touch_chat(chat.id, chat.type, chat.title)
                    _SEEN_CHATS.add(chat.id)
                except Exception:  # noqa: BLE001
                    log.exception("Не смог запомнить чат %s", chat.id)
    return await handler(event, data)


@router.my_chat_member()
async def on_my_chat_member(update: ChatMemberUpdated, db: Database) -> None:
    chat = update.chat
    if chat.type not in ("group", "supergroup"):
        return
    if update.new_chat_member.status in ("left", "kicked"):
        await db.mark_chat_left(chat.id)
        _SEEN_CHATS.discard(chat.id)
    else:
        await db.touch_chat(chat.id, chat.type, chat.title)
        _SEEN_CHATS.add(chat.id)


async def broadcast_to_chats(bot: Bot, db: Database, text: str) -> str:
    """Шлёт сообщение во все живые группы. В лички не отправляет."""
    targets = await db.broadcast_targets()
    if not targets:
        return (
            "Пока не знаю ни одной группы. Добавь бота в чат или напиши в нём "
            "любую команду — и он её запомнит."
        )
    sent, failed = 0, 0
    for chat_id in targets:
        ok = False
        try:
            await bot.send_message(chat_id, text)
            ok = True
        except TelegramBadRequest:
            # скорее всего кривой HTML — пробуем отправить как обычный текст
            try:
                await bot.send_message(chat_id, text, parse_mode=None)
                ok = True
            except Exception:  # noqa: BLE001
                ok = False
        except Exception:  # noqa: BLE001
            ok = False
            await db.mark_chat_left(chat_id)
        if ok:
            sent += 1
            log.info("Рассылка ушла в чат %s", chat_id)
        else:
            failed += 1
            log.warning("Рассылка не дошла в чат %s", chat_id)
        await asyncio.sleep(0.05)
    return f"📣 Разослано в <b>{sent}</b> групп(ы). Не дошло: {failed}."


@router.message(Command("admin", "админ"))
async def cmd_admin(
    message: Message, db: Database, bot: Bot, boss_repo: BossRepo
) -> None:
    """Админка прямо в Telegram — доступна только id из ADMIN_IDS."""
    user = message.from_user
    if user is None:
        return
    if not settings.is_admin(user.id):
        await message.answer("🔒 Эта команда только для админа.")
        return

    raw = message.text or ""
    parts = raw.split()[1:]
    if not parts:
        await message.answer(f"<pre>{render.esc(admin_actions.HELP)}</pre>")
        return

    # /admin soo <текст> — рассылка по всем группам с ботом
    head = raw.split(maxsplit=2)
    if len(head) >= 2 and head[1].lower() in ("soo", "рассылка"):
        text = head[2].strip() if len(head) > 2 else ""
        if not text:
            await message.answer(
                "Формат: <code>/admin soo текст</code>\n"
                "Разошлю во все группы, где есть бот. В лички не отправляю."
            )
            return
        await message.answer(await broadcast_to_chats(bot, db, text))
        return

    # /admin boss [hp|имя] — запустить рейд-босса и разослать карточку.
    if len(head) >= 2 and head[1].lower() in ("boss", "босс"):
        arg = head[2].strip() if len(head) > 2 else ""
        if arg.isdigit():
            hp, name = int(arg), boss.DEFAULT_NAME
        elif arg:
            hp, name = boss.DEFAULT_HP, arg
        else:
            hp, name = boss.DEFAULT_HP, boss.DEFAULT_NAME
        raid = await boss_repo.start(name, hp, message.chat.id)
        # Карточку шлём прямо сюда, чтобы было куда тыкать, и в остальные группы.
        card_text, card_keyboard = await _boss_view(boss_repo, raid)
        here = await message.answer(card_text, reply_markup=card_keyboard)
        if here is not None and message.chat is not None:
            await boss_repo.attach(raid["id"], message.chat.id, here.message_id)
        sent = await broadcast_boss(
            bot, db, boss_repo, raid, exclude=message.chat.id
        )
        await message.answer(
            f"👹 Рейд запущен: <b>{render.esc(name)}</b> · {hp} HP · "
            f"удар {boss.HIT_DAMAGE}. Ещё разослал в {sent} групп(ы).\n"
            "Карты не нужны — жми «Ударить»."
        )
        return

    # /admin clicker [off] — кликер: тапают и получают подарки.
    if len(head) >= 2 and head[1].lower() in ("clicker", "кликер"):
        arg = head[2].strip().lower() if len(head) > 2 else ""
        if arg in ("off", "stop", "стоп", "выкл"):
            await db.set_setting("clicker_live", "0")
            await message.answer("👆 Кликер остановлен.")
            return
        await db.set_setting("clicker_live", "1")
        text, keyboard = render.render_clicker()
        await message.answer(text, reply_markup=keyboard)
        sent = await _broadcast_clicker(bot, db, exclude=message.chat.id)
        await message.answer(f"👆 Кликер запущен. Ещё разослал в {sent} групп(ы).")
        return

    try:
        result = await admin_actions.run(db, parts[0], parts[1:])
    except ValueError as error:
        await message.answer(f"⚠️ {render.esc(str(error))}")
        return
    except Exception:  # noqa: BLE001
        log.exception("Админ-команда %s упала", parts[0])
        await message.answer("⚠️ Не получилось, я записал ошибку в логи.")
        return
    await message.answer(f"<pre>{render.esc(result)}</pre>")


@router.message(Command("drop", "daily", "карта"))
@router.message(NormalizedText("северо-юг", "север юг", "северо юг"))
async def cmd_drop(message: Message, db: Database) -> None:
    user = message.from_user
    if user is None:
        return
    await db.ensure_player(user.id, user.username, user.first_name)

    today = day_key()
    left = await db.claim_daily(user.id, today, DROPS_PER_DAY)
    if left is None:
        seconds = (next_reset() - datetime.now(timezone.utc)).total_seconds()
        await message.reply(
            f"⏳ Попытки на сегодня кончились. Следующая — через {_humanize(seconds)} "
            "(сброс в 12:00 по ЕКБ)."
        )
        return

    card = roll_card()
    counts = await db.get_collection(user.id)
    is_new = card.card_id not in counts
    count = await db.add_card(user.id, card.card_id)
    await db.add_points(user.id, card.points)
    await db.add_drop(user.id, message.chat.id, card.card_id, today)

    text = render.render_drop(card, count, is_new)
    if left:
        text += f"\n\n🎟 Осталось попыток сегодня: <b>{left}</b>"
    await message.reply(text)


def upgrade_items(row: dict[str, Any]) -> list[str]:
    """Читаемые названия прикреплённых улучшений."""
    out: list[str] = []
    for slot in ("aura", "background", "effect"):
        item = item_of(slot, row.get(f"{slot}_id"))
        if item:
            out.append(f"{SLOT_ICONS[slot]} {item.name} ({item.summary})")
    return out


def decorate_lot(lot: dict[str, Any]) -> dict[str, Any]:
    """Досчитывает статы и разворачивает улучшения для отображения лота.

    У кейса нет карты: card_id в базе NULL, поэтому статы не считаем —
    иначе get_card(None) роняет весь список рынка.
    """
    bonus = lot.get("bonus") or {}
    lot["bonus"] = bonus
    lot["stats"] = None
    for slot in ("aura", "background", "effect"):
        lot[slot] = None

    if lot.get("kind") == "case" or not lot.get("card_id"):
        return lot

    card = get_card(lot["card_id"])
    lot["stats"] = effective_stats(card, bonus)
    for slot in ("aura", "background", "effect"):
        item = item_of(slot, lot.get(f"{slot}_id"))
        if item is not None:
            lot[slot] = {
                "name": item.name,
                "icon": SLOT_ICONS[slot],
                "summary": item.summary,
            }
    return lot


async def collection_data(
    db: Database, market: MarketRepo, user_id: int
) -> tuple[str, list[dict[str, Any]]]:
    """Текст коллекции и список карт для кнопок."""
    counts = await db.get_collection(user_id)
    kills = await db.get_card_kills(user_id)
    stats = await db.collection_stats(user_id)
    cards = cards_sorted_for_user(list(counts))

    instances = []
    for row in await market.user_inventory(user_id):
        if row["card_id"] not in CARDS_BY_ID:
            # карта удалена из каталога, а у игрока запись осталась — пропускаем
            continue
        card = get_card(row["card_id"])
        instances.append(
            {
                "inventory_id": row["id"],
                "card": card,
                "stats": effective_stats(card, row["bonus"]),
                "items": upgrade_items(row),
                "bonus": row["bonus"],
                "casino_bonus": row.get("casino_bonus") or {},
            }
        )
    cases = await db.user_cases(user_id)
    text = render.render_collection(
        cards, counts, kills, stats, len(CARDS), instances, cases
    )
    units: list[dict[str, Any]] = [
        {
            "handle": f"#{card.card_id}",
            "card": card,
            "count": counts[card.card_id],
            "bonus": {},
            "stats": effective_stats(card, {}),
            "inventory_id": None,
            "kills": kills.get(card.card_id, 0),
        }
        for card in cards
    ]
    units.extend(
        {
            "handle": f"#{inst['inventory_id']}",
            "card": inst["card"],
            "count": 1,
            "bonus": inst["bonus"],
            "stats": inst["stats"],
            "inventory_id": inst["inventory_id"],
            "items": inst["items"],
            "kills": kills.get(inst["card"].card_id, 0),
        }
        for inst in instances
    )
    # аксессуары надеваются на конкретную карту и меняют её статы
    for unit in units:
        extra = await db.accessory_bonus(user_id, unit["card"].card_id)
        if extra:
            merged = sum_bonus(unit.get("bonus") or {}, extra)
            unit["bonus"] = merged
            unit["stats"] = effective_stats(unit["card"], merged)
            unit["accessories"] = extra
    return text, units


@router.message(Command("my", "collection", "cards"))
async def cmd_collection(message: Message, db: Database, market: MarketRepo) -> None:
    user = message.from_user
    if user is None:
        return
    await db.ensure_player(user.id, user.username, user.first_name)
    text, keyboard = await _my_home_text(db, market, user.id)
    await message.answer(text, reply_markup=keyboard)


async def resolve_profile_target(
    message: Message, market: MarketRepo
) -> tuple[int | None, str | None, str | None]:
    """Кого смотреть: (id, имя, ошибка). id=None — свой профиль."""
    reply = message.reply_to_message
    if reply is not None and reply.from_user is not None and not reply.from_user.is_bot:
        return reply.from_user.id, reply.from_user.first_name, None
    for part in (message.text or "").split()[1:]:
        if part.startswith("@"):
            found = await market.find_by_username(part)
            if found is None:
                return None, None, (
                    f"Игрок {render.esc(part)} не найден. Он должен хотя бы раз "
                    "написать боту — тогда я его узнаю."
                )
            return int(found["user_id"]), found["first_name"], None
    for entity in message.entities or []:
        if entity.type == "text_mention" and entity.user is not None:
            return entity.user.id, entity.user.first_name, None
    return None, None, None


async def _profile_extra(db: Database, user_id: int) -> str:
    """Статус, описание, музыка, теги и награды — то, что игрок оформил сам."""
    prof = await db.profile_get(user_id)
    tags = await db.profile_tags(user_id)
    rewards = await db.profile_rewards(user_id)
    lines: list[str] = []
    if tags:
        lines.append(" ".join(profiles.tag_label(tag) for tag in tags))
    if prof["status"]:
        lines.append(f"💬 {render.esc(prof['status'])}")
    if prof["bio"]:
        lines.append(f"«{render.esc(prof['bio'])}»")
    if prof["music"]:
        lines.append(f"🎵 {render.esc(prof['music'])}")
    for reward in rewards:
        lines.append(f"{render.esc(str(reward['icon']))} {render.esc(str(reward['text']))}")
    return "\n".join(lines)


@router.message(Command("profile", "me", "профиль"))
@router.message(NormalizedText("профиль", "мой профиль"))
async def cmd_profile(
    message: Message, db: Database, market: MarketRepo, bot: Bot
) -> None:
    user = message.from_user
    if user is None:
        return
    target_id, target_name, error = await resolve_profile_target(message, market)
    if error:
        await message.answer(f"⚠️ {error}")
        return
    if target_id is None:
        target_id, target_name = user.id, user.first_name
    await db.ensure_player(target_id, None, target_name)
    profile = await db.player_profile(target_id)
    if profile is None:
        await message.answer("Профиль пока пуст. Напиши «Северо-Юг».")
        return
    extra = await _profile_extra(db, target_id)
    text = render.render_profile(profile, len(CARDS))
    if extra:
        head, _, body = text.partition("\n")
        text = head + "\n" + extra + "\n" + body
    keyboard = render.profile_keyboard(target_id, is_owner=target_id == user.id)
    base = _base_url()
    if base and message.chat.type == "private":
        from aiogram.types import WebAppInfo

        link = f"{base}/profile" + ("" if target_id == user.id else f"?u={target_id}")
        keyboard.inline_keyboard.insert(
            0,
            [
                InlineKeyboardButton(
                    text="🎨 Открыть профиль в приложении",
                    web_app=WebAppInfo(url=link),
                )
            ],
        )
    await _send_profile(message, bot, target_id, text, keyboard)


@router.message(Command("find", "поиск", "search"))
@router.message(NormalizedText("поиск"))
async def cmd_find(message: Message, db: Database) -> None:
    parts = (message.text or "").split(maxsplit=1)
    query = parts[1].strip() if len(parts) > 1 else ""
    if len(query.lstrip("@")) < 2:
        await message.answer(
            "🔎 <b>Поиск игроков</b>\n\n"
            "Напиши: <code>/find имя</code> — покажу, кто есть.\n"
            "Дальше <code>/profile @ник</code> откроет его профиль."
        )
        return
    from . import levels

    rows = await db.profile_find(query)
    if not rows:
        await message.answer(f"По запросу «{render.esc(query)}» никого не нашёл.")
        return
    lines = ["🔎 <b>Нашёл:</b>", ""]
    for row in rows:
        name = row["first_name"] or row["username"] or "игрок"
        nick = f" @{row['username']}" if row["username"] else ""
        level = levels.level_from_xp(int(row["xp"] or 0))
        lines.append(f"· <b>{render.esc(name)}</b>{render.esc(nick)} — ур. {level}")
    lines += ["", "Открыть: <code>/profile @ник</code>"]
    await message.answer("\n".join(lines))


@router.callback_query(F.data.startswith("pf:"))
async def cb_profile(
    callback: CallbackQuery, db: Database, market: MarketRepo, bot: Bot
) -> None:
    assert callback.data is not None
    parts = callback.data.split(":", 3)
    target_id = int(parts[1])
    action = parts[2] if len(parts) > 2 else "back"
    handle = parts[3] if len(parts) > 3 else None
    is_owner = callback.from_user.id == target_id

    if action == "back":
        profile = await db.player_profile(target_id)
        if profile is None:
            await callback.answer("Профиль не найден", show_alert=True)
            return
        await _edit_profile(
            callback,
            bot,
            target_id,
            render.render_profile(profile, len(CARDS)),
            render.profile_keyboard(target_id, is_owner),
        )
        await callback.answer()
        return

    if action == "cards" and is_owner:
        # Свои карты — в новом постраничном меню, старое не тянем.
        counts = await db.get_collection(target_id)
        text, keyboard = render.my_cards(
            cards_sorted_for_user(list(counts)), counts, 0
        )
        await _safe_edit(callback, text, keyboard)
        await callback.answer()
        return

    if action in ("cards", "c"):
        # Чужие карты — тоже новое постраничное меню, только для просмотра.
        page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
        counts = await db.get_collection(target_id)
        text, keyboard = render.my_cards(
            cards_sorted_for_user(list(counts)),
            counts,
            page,
            prefix=f"pf:{target_id}",
            header="Карты игрока",
            middle=f"pf:{target_id}:back",
        )
        await _safe_edit(callback, text, keyboard)
        await callback.answer()
        return

    if action == "d" and handle:
        _, units = await collection_data(db, market, target_id)
        unit = next((item for item in units if item["handle"] == handle), None)
        if unit is None:
            await callback.answer("Карта не найдена", show_alert=True)
            return
        text, keyboard = render.render_card_detail(unit, target_id, False)
        await _safe_edit(callback, text, keyboard)
        await callback.answer()
        return

    if action == "card" and handle:
        _, units = await collection_data(db, market, target_id)
        unit = next((item for item in units if item["handle"] == handle), None)
        if unit is None:
            await callback.answer("Карта не найдена", show_alert=True)
            return
        text, keyboard = render.render_card_detail(unit, target_id, is_owner)
        await _safe_edit(callback, text, keyboard)
        await callback.answer()
        return

    await callback.answer()


@router.message(Command("pvprating", "пвптоп", "pvp_top"))
@router.message(NormalizedText("пвптоп", "пвп топ"))
async def cmd_pvp_rating(message: Message, db: Database) -> None:
    rows = await db.rating(10)
    await message.answer(render.render_rating(rows))


@router.message(Command("top", "leaderboard"))
@router.message(NormalizedText("топ", "топ игроков", "топ по очкам"))
async def cmd_top(message: Message, db: Database) -> None:
    rows = await db.top_players(10)
    lines = ["🏆 <b>Топ по очкам</b>", ""]
    if not rows:
        lines.append("Пока никто не собрал ни одной карты.")
    medals = ["🥇", "🥈", "🥉"]
    for index, row in enumerate(rows):
        name = row["first_name"] or row["username"] or f"id{row['user_id']}"
        place = medals[index] if index < 3 else f"{index + 1}."
        lines.append(
            f"{place} {render.esc(name)} — <b>{row['points']}</b> очк. · {row['unique_cards']} карт"
        )
    await message.answer("\n".join(lines))


@router.message(Command("pvp", "бой"))
@router.message(NormalizedText("пвп", "pvp"))
async def cmd_pvp(message: Message, db: Database, service: BattleService) -> None:
    user = message.from_user
    if user is None:
        return
    reply = message.reply_to_message
    if reply is None or reply.from_user is None:
        await message.reply(
            "⚔️ Чтобы вызвать на бой, ответь командой <b>пвп</b> на сообщение соперника."
        )
        return
    await db.ensure_player(user.id, user.username, user.first_name)
    try:
        await service.create(message, user, reply.from_user)
    except BattleError as error:
        await message.reply(f"⚠️ {error}")
    except Exception:  # noqa: BLE001
        log.exception("Не удалось создать бой")
        await message.reply("⚠️ Не получилось создать бой, попробуй ещё раз.")


# --------------------------------------------------------------------------- #
# Callback-и
# --------------------------------------------------------------------------- #


@router.callback_query(F.data.startswith("b:"))
async def cb_battle(callback: CallbackQuery, service: BattleService) -> None:
    assert callback.data is not None
    _, battle_id, action = callback.data.split(":", 2)
    try:
        if action == "noop":
            await callback.answer("Бой завершён")
            return
        if action == "flee":
            await service.surrender(callback, battle_id)
        else:
            await service.act(callback, battle_id, action)
    except BattleError as error:
        await callback.answer(str(error), show_alert=True)
        return
    await callback.answer()


@router.callback_query(F.data.startswith("pick:"))
async def cb_pick_page(callback: CallbackQuery, service: BattleService) -> None:
    assert callback.data is not None
    _, battle_id, page = callback.data.split(":", 2)
    try:
        await service.repaginate(callback, battle_id, int(page))
    except BattleError as error:
        await callback.answer(str(error), show_alert=True)
        return
    await callback.answer()


@router.callback_query(F.data.startswith("pickc:"))
async def cb_pick_card(callback: CallbackQuery, service: BattleService) -> None:
    assert callback.data is not None
    _, battle_id, card_id = callback.data.split(":", 2)
    try:
        await service.choose_card(callback, battle_id, card_id)
    except BattleError as error:
        await callback.answer(str(error), show_alert=True)
        return
    await callback.answer("Карта выбрана")


@router.callback_query(F.data.startswith("noop"))
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


# --------------------------------------------------------------------------- #
# Рынок карт
# --------------------------------------------------------------------------- #


async def _market_view(market: MarketRepo, user_id: int, page: int):
    total = await market.count_lots()
    pages = max(1, (total + MARKET_PAGE_SIZE - 1) // MARKET_PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    lots = [
        decorate_lot(lot)
        for lot in await market.list_lots(MARKET_PAGE_SIZE, page * MARKET_PAGE_SIZE)
    ]
    balance = await market.balance(user_id)
    return render.render_market(lots, page, pages, total, balance)


async def _safe_edit(callback: CallbackQuery, text: str, keyboard) -> None:
    message = callback.message
    if message is None:
        return
    # Ничего страшного: Telegram просто просит сбавить темп.
    _ = text
    # Фото нельзя превратить в текст: если предыдущий экран был с артом,
    # убираем его и шлём новое сообщение. Иначе старая картинка оставалась
    # и «карточка» открывалась под чужим артом (например, Гузель).
    if getattr(message, "photo", None):
        with contextlib.suppress(Exception):
            await message.delete()
        with contextlib.suppress(Exception):
            await callback.bot.send_message(
                chat_id=message.chat.id,
                message_thread_id=getattr(message, "message_thread_id", None),
                text=text,
                reply_markup=keyboard,
            )
        return
    try:
        await message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest as error:
        if "not modified" not in str(error).lower():
            log.warning("Не удалось обновить сообщение: %s", error)


@router.message(Command("market", "рынок"))
async def cmd_market(
    message: Message, db: Database, market: MarketRepo, bot: Bot
) -> None:
    user = message.from_user
    if user is None:
        return
    await db.ensure_player(user.id, user.username, user.first_name)
    text, keyboard = await _market_view(market, user.id, 0)
    await message.answer(text, reply_markup=keyboard)
    base = _base_url()
    if base and message.chat.type == "private":
        from aiogram.types import WebAppInfo

        await message.answer(
            "🏪 А ещё рынок открывается приложением — с артами и покупкой в один тап.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🏪 Открыть рынок",
                            web_app=WebAppInfo(url=f"{base}/market"),
                        )
                    ]
                ]
            ),
        )
    elif base:
        # В группах Telegram запрещает кнопки мини-апп — даём ссылку в личку.
        username = await _bot_username(bot) if bot else ""
        if username:
            await message.answer(
                "🏪 Рынок приложением открывается в личке со мной — "
                "у меня там кнопка «Рынок» рядом с полем ввода.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🏪 Открыть бота",
                                url=f"https://t.me/{username}",
                            )
                        ]
                    ]
                ),
            )


@router.callback_query(F.data.startswith("mk:"))
async def cb_market_page(callback: CallbackQuery, market: MarketRepo) -> None:
    assert callback.data is not None
    page = int(callback.data.split(":", 1)[1])
    text, keyboard = await _market_view(market, callback.from_user.id, page)
    await _safe_edit(callback, text, keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("ml:"))
async def cb_lot_view(callback: CallbackQuery, market: MarketRepo) -> None:
    assert callback.data is not None
    lot_id = int(callback.data.split(":", 1)[1])
    lot = await market.get_lot(lot_id)
    if lot is None:
        await callback.answer("Лот не найден", show_alert=True)
        return
    lot = decorate_lot(lot)
    balance = await market.balance(callback.from_user.id)
    text, keyboard = render.render_lot(lot, callback.from_user.id, balance)
    await _safe_edit(callback, text, keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("mb:"))
async def cb_buy(callback: CallbackQuery, market: MarketRepo) -> None:
    assert callback.data is not None
    lot_id = int(callback.data.split(":", 1)[1])
    try:
        result = await market.buy_lot(lot_id, callback.from_user.id)
    except MarketError as error:
        await callback.answer(str(error), show_alert=True)
        return
    if result.get("kind") == "case":
        await callback.answer("Куплено: кейс 📦", show_alert=True)
    else:
        card = get_card(result["card_id"])
        await callback.answer(f"Куплено: {card.display_name}", show_alert=True)
    text, keyboard = await _market_view(market, callback.from_user.id, 0)
    await _safe_edit(callback, text, keyboard)


@router.callback_query(F.data.startswith("mx:"))
async def cb_lot_cancel(callback: CallbackQuery, market: MarketRepo) -> None:
    assert callback.data is not None
    lot_id = int(callback.data.split(":", 1)[1])
    try:
        await market.cancel_lot(lot_id, callback.from_user.id)
    except MarketError as error:
        await callback.answer(str(error), show_alert=True)
        return
    await callback.answer("Лот снят, карта вернулась", show_alert=True)
    text, keyboard = await _market_view(market, callback.from_user.id, 0)
    await _safe_edit(callback, text, keyboard)


@router.message(Command("sell", "продать"))
async def cmd_sell(message: Message, db: Database, market: MarketRepo) -> None:
    user = message.from_user
    if user is None:
        return
    await db.ensure_player(user.id, user.username, user.first_name)
    parts = (message.text or "").split()[1:]
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer(
            "Формат: <code>/sell #id цена</code>\n"
            "Например: <code>/sell #oleg 1500</code> или <code>/sell #12 9000</code>\n"
            "Свои карты и их id — в /my"
        )
        return
    handle, price = parts[0], int(parts[1])
    if price < 1:
        await message.answer("Цена должна быть больше нуля.")
        return
    parsed = parse_handle(handle)
    if parsed is None:
        await message.answer("Не понял, какую карту продать. Загляни в /my")
        return
    try:
        unit = await market.owned_unit(user.id, parsed)
        lot = await market.create_lot(user.id, unit, price)
    except MarketError as error:
        await message.answer(f"⚠️ {error}")
        return

    if unit.get("kind") == "case":
        info = await market.rating_info(user.id)
        await message.answer(
            render.render_sell_case(lot, lot["ratio"], lot["penalty"], info["rating"])
        )
        return

    card = get_card(lot["card_id"])
    lines = [
        f"✅ Лот <code>#{lot['id']}</code> выставлен",
        f"{card.rarity_emoji} <b>{render.esc(card.display_name)}</b> за <b>{price}</b> очк.",
        f"Рыночная цена ~{lot['reference']} — это {lot['ratio'] * 100:.0f}%",
    ]
    if lot["penalty"]:
        info = await market.rating_info(user.id)
        lines.append(
            f"⚠️ Слишком дешёво: репутация {lot['penalty']:+.1f} → {info['rating']:.2f}"
        )
    if lot["suspect"]:
        lines.append("🚩 Лот помечен как подозрительный.")
    lines.append(f"Изменить цену: <code>/changeprice {lot['id']} новая_цена</code>")
    await message.answer("\n".join(lines))


@router.message(Command("mylots", "лоты"))
async def cmd_mylots(message: Message, market: MarketRepo) -> None:
    user = message.from_user
    if user is None:
        return
    lots = await market.seller_lots(user.id)
    if not lots:
        await message.answer("У тебя нет активных лотов. Выставить: /sell #id цена")
        return
    lines = ["📦 <b>Твои лоты</b>", ""]
    for lot in lots:
        if lot.get("kind") == "case" or not lot.get("card_id"):
            title = "📦 <b>Кейс</b>"
        else:
            card = get_card(lot["card_id"])
            title = f"{card.rarity_emoji} {render.esc(card.display_name)}"
        lines.append(
            f"<code>#{lot['id']}</code> {title} — "
            f"<b>{lot['price']}</b> очк. (рынок {lot['market_price']})"
            + (" 🚩" if lot["suspect"] else "")
        )
    lines.append("")
    lines.append("Снять: кнопка на лоте в /market. Цена: /changeprice id цена")
    await message.answer("\n".join(lines))


@router.message(Command("changeprice", "цена"))
async def cmd_changeprice(message: Message, market: MarketRepo) -> None:
    user = message.from_user
    if user is None:
        return
    parts = (message.text or "").split()[1:]
    lot_id = next((int(p.lstrip("#")) for p in parts if p.lstrip("#").isdigit()), None)
    price = next((int(p) for p in parts[::-1] if p.isdigit()), None)
    if lot_id is None or price is None or price < 1:
        await message.answer("Формат: <code>/changeprice 12 9000</code>")
        return
    try:
        lot = await market.change_price(lot_id, user.id, price)
    except MarketError as error:
        await message.answer(f"⚠️ {error}")
        return
    lines = [f"✅ Цена лота <code>#{lot_id}</code> → <b>{price}</b> очк."]
    if lot.get("suspect"):
        lines.append("🚩 Лот помечен как подозрительный.")
    await message.answer("\n".join(lines))


@router.message(Command("gift", "подарить"))
async def cmd_gift(message: Message, db: Database, market: MarketRepo) -> None:
    user = message.from_user
    if user is None:
        return
    await db.ensure_player(user.id, user.username, user.first_name)
    parts = (message.text or "").split()[1:]
    if not parts:
        await message.answer("Формат: ответом на сообщение — <code>/gift #id</code>")
        return
    parsed = parse_handle(parts[0])
    if parsed is None:
        await message.answer("Не понял, какую карту подарить. Загляни в /my")
        return

    target_id: int | None = None
    target_name = "получатель"
    reply = message.reply_to_message
    if reply is not None and reply.from_user is not None and not reply.from_user.is_bot:
        target_id = reply.from_user.id
        target_name = reply.from_user.first_name or "получатель"
    if target_id is None:
        for part in parts[1:]:
            if part.startswith("@"):
                found = await market.find_by_username(part)
                if found:
                    target_id = int(found["user_id"])
                    target_name = found["first_name"] or part
                    break
    if target_id is None:
        for entity in message.entities or []:
            if entity.type == "text_mention" and entity.user is not None:
                target_id = entity.user.id
                target_name = entity.user.first_name or "получатель"
                break
    if target_id is None:
        await message.answer(
            "Не понял получателя. Ответь командой <code>/gift #id</code> "
            "на его сообщение или укажи <code>@username</code> того, кто уже играл."
        )
        return

    try:
        unit = await market.owned_unit(user.id, parsed)
        await market.gift_card(user.id, unit, target_id)
    except MarketError as error:
        await message.answer(f"⚠️ {error}")
        return

    if unit.get("kind") == "case":
        title = "📦 <b>Кейс</b>"
    else:
        card = get_card(unit["card_id"])
        title = f"{card.rarity_emoji} <b>{render.esc(card.display_name)}</b>"
    await message.answer(f"🎁 Подарок отправлен: {title} → {render.esc(target_name)}")


# --------------------------------------------------------------------------- #
# Кликер: тапают все, что-то падает
# --------------------------------------------------------------------------- #

_CLICKER_TAPS: dict[int, float] = {}


async def _broadcast_clicker(
    bot: Bot, db: Database, exclude: int | None = None
) -> int:
    text, keyboard = render.render_clicker()
    sent = 0
    for chat_id in await db.broadcast_targets():
        if exclude is not None and int(chat_id) == int(exclude):
            continue
        try:
            await bot.send_message(chat_id, text, reply_markup=keyboard)
        except Exception:  # noqa: BLE001
            continue
        sent += 1
        await asyncio.sleep(0.05)
    return sent


@router.callback_query(F.data == "clicker:tap")
async def cb_clicker(callback: CallbackQuery, db: Database) -> None:
    """Тап по кликеру: случайная награда, в основном очки."""
    user = callback.from_user
    if (await db.get_setting("clicker_live")) != "1":
        await callback.answer("Кликер выключен.", show_alert=True)
        return
    now = time.monotonic()
    if now - _CLICKER_TAPS.get(user.id, 0.0) < clicker.TAP_COOLDOWN_SECONDS:
        await callback.answer("Не так часто 🙂")
        return
    _CLICKER_TAPS[user.id] = now
    await db.ensure_player(user.id, user.username, user.first_name)
    kind, value = clicker.roll_reward()
    if kind == clicker.POINTS:
        await db.add_points(user.id, int(value))
    elif kind == clicker.DROP:
        await db.grant_drop_limit(user.id, day_key(), 1, DROPS_PER_DAY)
    elif kind == clicker.SPIN:
        await db.grant_spin_limit(user.id, roulette_day_key(), 1, SPINS_PER_DAY)
    elif kind == clicker.CASE:
        await db.add_case(user.id, "clicker")
    else:
        card = value
        await db.add_card(user.id, card.card_id)
        await db.add_points(user.id, card.points)
    answer = clicker.label(kind, value)
    rare = kind != clicker.POINTS
    await callback.answer(answer, show_alert=rare)
    if rare and callback.message is not None:
        with contextlib.suppress(Exception):
            await callback.message.reply(f"🎉 {user.first_name} выбил {answer}")


# --------------------------------------------------------------------------- #
# ОБНОВЛЕНИЕ: рубильник новых мини-аппок (кейсы и рулетка)
# --------------------------------------------------------------------------- #

UPDATE_ANNOUNCE = (
    "🚀 <b>ОБНОВЛЕНИЕ!</b>\n\n"
    "♻️ <b>Апгрейдер карт</b> — как в CS:GO. Кладёшь свою карту в первый слот, "
    "выбираешь желаемую во второй, и крутится рулетка с шансом.\n"
    "С эпика на мифика ~20%, а с обычного Олега на ультра-Леру — 0.1%. "
    "Только карты, ничего другого.\n\n"
    "📦 Кейсы теперь открываются как в CS:GO — крутится лента, и видно, что выпало.\n"
    "🎡 Рулетка стала настоящим колесом с призами и шансами.\n\n"
    "Всё это — в мини-аппке, жми кнопку ниже."
)


async def _miniapps_live(db: Database) -> bool:
    """Обновление включается, только когда админ напишет ОБНОВЛЕНИЕ."""
    return (await db.get_setting("miniapps_live")) == "1"


def _link_keyboard(username: str, chat_type: str) -> InlineKeyboardMarkup:
    """web_app-кнопки Telegram разрешает только в личке. В группах — ссылка,
    которая открывает личку с ботом и уже там показывает мини-аппку."""
    if chat_type == "private":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📦 Кейсы", url=f"https://t.me/{username}?start=caseapp")],
                [InlineKeyboardButton(text="🎡 Рулетка", url=f"https://t.me/{username}?start=rouletteapp")],
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📦 Кейсы — в личке", url=f"https://t.me/{username}?start=caseapp")],
            [InlineKeyboardButton(text="🎡 Рулетка — в личке", url=f"https://t.me/{username}?start=rouletteapp")],
        ]
    )


async def _send_miniapp(message: Message, bot: Bot, kind: str) -> None:
    """Кнопка на мини-аппку кейсов или рулетки."""
    base = _base_url()
    if kind == "case":
        label, path = "📦 Открыть кейсы", "/case_app"
    else:
        label, path = "🎡 Крутить рулетку", "/roulette_app"
    if message.chat.type == "private" and base:
        from aiogram.types import WebAppInfo

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=label, web_app=WebAppInfo(url=f"{base}{path}")
                    )
                ]
            ]
        )
        await message.answer("Открывай:", reply_markup=keyboard)
        return
    username = await _bot_username(bot)
    payload = "caseapp" if kind == "case" else "rouletteapp"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{label} — в личке",
                    url=f"https://t.me/{username}?start={payload}",
                )
            ]
        ]
    )
    await message.answer(
        "Мини-аппка открывается в личке со мной — жми кнопку:", reply_markup=keyboard
    )


async def _broadcast_update(
    bot: Bot, db: Database, username: str, exclude: int | None = None
) -> int:
    sent = 0
    for chat_id in await db.broadcast_targets():
        if exclude is not None and int(chat_id) == int(exclude):
            continue
        try:
            await bot.send_message(
                chat_id, UPDATE_ANNOUNCE, reply_markup=_link_keyboard(username, "group")
            )
        except Exception:  # noqa: BLE001
            continue
        sent += 1
        await asyncio.sleep(0.05)
    for user_id in await db.all_player_ids():
        try:
            await bot.send_message(
                user_id, UPDATE_ANNOUNCE, reply_markup=_link_keyboard(username, "private")
            )
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(0.05)
    return sent


@router.message(UpdateWord())
async def cmd_update_live(message: Message, bot: Bot, db: Database) -> None:
    """Рубильник: пока админ молчит, новых мини-аппок для игроков нет."""
    user = message.from_user
    if user is None or not settings.is_admin(user.id):
        return
    await db.set_setting("miniapps_live", "1")
    username = await _bot_username(bot)
    await message.answer(
        UPDATE_ANNOUNCE, reply_markup=_link_keyboard(username, message.chat.type)
    )
    sent = await _broadcast_update(
        bot, db, username, exclude=message.chat.id
    )
    await message.answer(f"✅ Обновление включено. Разослал ещё в {sent} групп(ы).")


# --------------------------------------------------------------------------- #
# Рулетка и кейсы
# --------------------------------------------------------------------------- #


@router.message(Command("roulette", "рулетка"))
@router.message(NormalizedText("рулетка", "руль"))
async def cmd_roulette(
    message: Message, db: Database, market: MarketRepo, bot: Bot
) -> None:
    user = message.from_user
    if user is None:
        return
    await db.ensure_player(user.id, user.username, user.first_name)

    if await _miniapps_live(db):
        await _send_miniapp(message, bot, "roulette")
        return

    spins_left = await db.claim_roulette(user.id, roulette_day_key(), SPINS_PER_DAY)
    if spins_left is None:
        seconds = (next_roulette_reset() - datetime.now(timezone.utc)).total_seconds()
        await message.reply(
            f"⏳ Спины на сегодня кончились. Следующий — через {_humanize(seconds)} "
            "(в 20:00 по ЕКБ)."
        )
        return

    kind, value = roll_prize()
    if kind == PRIZE_POINTS:
        await db.add_points(user.id, int(value))
    elif kind == PRIZE_CASE:
        case_id = await db.add_case(user.id, "roulette")
        log.info("Кейс #%s выпал игроку %s", case_id, user.id)
    else:
        card = get_card(str(value))
        await db.add_card(user.id, card.card_id)
        await db.add_points(user.id, card.points)

    balance = await market.balance(user.id)
    text = render.render_roulette(kind, value, balance)
    if spins_left:
        text += f"\n\n🎟 Осталось спинов сегодня: <b>{spins_left}</b>"
    await message.reply(text)


@router.message(Command("case", "кейс", "открыть"))
@router.message(NormalizedText("кейс", "открыть кейс"))
async def cmd_case(message: Message, db: Database, bot: Bot) -> None:
    user = message.from_user
    if user is None:
        return
    await db.ensure_player(user.id, user.username, user.first_name)

    if await _miniapps_live(db):
        await _send_miniapp(message, bot, "case")
        return

    cases = await db.user_cases(user.id)
    if not cases:
        await message.answer(
            "📦 Кейсов нет. Крути рулетку: /roulette — или купи кейс на рынке: /market"
        )
        return

    limit = await db.case_limit(user.id)
    if limit["left"] <= 0:
        await message.answer(
            "📦 <b>Лимит на сегодня</b>\n\n"
            f"Кейсы открываются не больше {OPEN_PER_DAY} раз в сутки.\n"
            "Приходи завтра."
        )
        return
    if limit["wait"] > 0:
        await message.answer(
            f"⏳ Кейсы открываются раз в минуту.\nПодожди ещё <b>{limit['wait']} сек.</b>"
        )
        return
    case = cases[0]
    if not await db.open_case(user.id, case["id"]):
        await message.answer("Этот кейс уже открыт или выставлен на продажу.")
        return

    card = roll_case_card()
    counts = await db.get_collection(user.id)
    is_new = card.card_id not in counts
    count = await db.add_card(user.id, card.card_id)
    await db.add_points(user.id, card.points)
    left = len(await db.user_cases(user.id))
    await message.answer(render.render_case_open(card, is_new, count, left))

@router.message(Command("upgrade", "улучшить"))
async def cmd_upgrade(message: Message, db: Database, market: MarketRepo) -> None:
    user = message.from_user
    if user is None:
        return
    await db.ensure_player(user.id, user.username, user.first_name)
    parts = (message.text or "").split()[1:]
    if not parts:
        await message.answer(
            "Формат: <code>/upgrade #id</code>\n"
            "Например: <code>/upgrade #oleg</code> — улучшит одну копию из стака.\n"
            f"Стоит <b>{UPGRADE_PRICE}</b> очков. За раз выдаёт сразу ауру, фон и эффект, "
            "все три случайные. Перебить нельзя."
        )
        return
    parsed = parse_handle(parts[0])
    if parsed is None:
        await message.answer("Не понял карту. Загляни в /my")
        return
    try:
        if parsed[0] == "card":
            outcome = await market.upgrade_stack(user.id, str(parsed[1]))
        elif parsed[0] == "inventory":
            outcome = await market.upgrade_instance(user.id, int(parsed[1]))
        else:
            await message.answer("Кейсы не улучшаются — их открывают: /case")
            return
    except MarketError as error:
        await message.answer(f"⚠️ {error}")
        return

    card = get_card(outcome["card_id"])
    await message.answer(
        render.render_upgrade(
            card, outcome["items"], outcome["balance"], outcome["inventory_id"]
        )
    )


@router.message(Command("rating", "репутация", "rep"))
async def cmd_rating(message: Message, db: Database, market: MarketRepo) -> None:
    user = message.from_user
    if user is None:
        return
    target_id = user.id
    target_name = None
    reply = message.reply_to_message
    if reply is not None and reply.from_user is not None:
        target_id = reply.from_user.id
        target_name = reply.from_user.first_name
    else:
        for part in (message.text or "").split()[1:]:
            if part.startswith("@"):
                found = await market.find_by_username(part)
                if found is None:
                    await message.answer(
                        f"Игрок {render.esc(part)} не найден. Пусть он сначала напишет боту, "
                        "либо ответь на его сообщение."
                    )
                    return
                target_id = int(found["user_id"])
                target_name = found["first_name"]
                break

    await db.ensure_player(target_id, None, target_name)
    profile = await market.rating_profile(target_id)
    if profile is None:
        await message.answer("Профиль не найден.")
        return
    stats = await market.deal_stats(target_id)
    await message.answer(render.render_rating_profile(profile, stats["deals"], stats["gifts"]))


# --------------------------------------------------------------------------- #
# Казино
# --------------------------------------------------------------------------- #


async def _casino_parse_bet(
    raw: str, balance: int, market: MarketRepo, user_id: int
) -> tuple[str | None, str]:
    """Разбирает ставку очками или картой. (token, подпись) либо (None, ошибка)."""
    if raw.lstrip("-").isdigit():
        amount = int(raw)
        if amount < casino.MIN_BET or amount > casino.MAX_BET:
            return None, f"⚠️ Ставка от {casino.MIN_BET} до {casino.MAX_BET} очков."
        if balance < amount:
            return None, f"⚠️ Не хватает очков: ставишь {amount}, у тебя {balance}."
        return f"p:{amount}", f"💰 {amount} очков"

    parsed = parse_handle(raw)
    if parsed is None:
        return None, "Не понял ставку. Смотри /casino"
    try:
        unit = await market.owned_unit(user_id, parsed)
    except MarketError as error:
        return None, f"⚠️ {error}"
    if unit.get("kind") == "case":
        return None, (
            "⚠️ Кейс нельзя поставить в казино — его открывают (/case) "
            "или продают на рынке."
        )
    card = get_card(unit["card_id"])
    return "c:" + raw.lstrip("#"), f"{card.rarity_emoji} {render.esc(card.display_name)}"


async def _casino_stats(message: Message, db: Database, market: MarketRepo) -> None:
    """Статистика казино: своя, по @нику/нику/id или ответом на сообщение.

    Явный аргумент важнее ответа: иначе при ответе на чужое сообщение
    @ник молча игнорировался и показывался не тот игрок.
    """
    user = message.from_user
    if user is None:
        return

    args = [
        part
        for part in (message.text or "").split()[1:]
        if part.lower() not in {"stats", "стата", "статистика", "итоги"}
    ]

    target_id: int | None = None
    target_name: str | None = None

    # упоминание игрока через выбор из списка (text_mention)
    for entity in message.entities or []:
        if entity.type == "text_mention" and entity.user is not None:
            target_id = entity.user.id
            target_name = entity.user.first_name
            break

    if target_id is None and args:
        found = await market.find_player(args[0])
        if found is None:
            await message.answer(
                f"Игрок {render.esc(args[0])} не найден. Укажи @ник "
                "или ответь на его сообщение."
            )
            return
        target_id = int(found["user_id"])
        target_name = found["first_name"]

    if target_id is None and message.reply_to_message is not None:
        replied = message.reply_to_message.from_user
        if replied is not None and not replied.is_bot:
            target_id = replied.id
            target_name = replied.first_name

    if target_id is None:
        target_id = user.id
        target_name = user.first_name

    await db.ensure_player(target_id, None, target_name)
    stats = await db.casino_stats(target_id)
    await message.answer(
        render.render_casino_stats(target_name or f"id{target_id}", stats)
    )


@router.message(Command("casinostats", "casinostat", "казиностата"))
@router.message(NormalizedText("казиностата", "стата казино"))
async def cmd_casino_stats(
    message: Message, db: Database, market: MarketRepo
) -> None:
    await _casino_stats(message, db, market)


@router.message(Command("casino", "казино"))
@router.message(NormalizedText("казино"))
async def cmd_casino(message: Message, db: Database, market: MarketRepo) -> None:
    user = message.from_user
    if user is None:
        return
    await db.ensure_player(user.id, user.username, user.first_name)
    balance = await market.balance(user.id)
    parts = (message.text or "").split()[1:]
    if parts and parts[0].lower() in {"stats", "стата", "статистика", "итоги"}:
        await _casino_stats(message, db, market)
        return
    if not parts:
        left = await db.casino_left(user.id, roulette_day_key(), casino.SPINS_PER_DAY)
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"➕ Купить крутку за {casino.EXTRA_SPIN_PRICE}",
                        callback_data="cspin",
                    )
                ]
            ]
        )
        await message.answer(
            render.render_casino_help(balance, left, casino.SPINS_PER_DAY),
            reply_markup=keyboard,
        )
        return

    # /casino кости 10000 и /casino 10000 кости — оба порядка работают.
    game = dice_casino.normalize_game(parts[0])
    bet_raw = parts[1] if len(parts) > 1 else None
    if game is None and len(parts) > 1:
        maybe = dice_casino.normalize_game(parts[1])
        if maybe is not None:
            game, bet_raw = maybe, parts[0]

    if game is not None:
        if bet_raw is None:
            await message.answer(
                f"{dice_casino.emoji(game)} <b>{dice_casino.title(game)}</b>\n\n"
                f"Формат: <code>/casino {parts[0]} 1000</code> "
                "или <code>/casino кости #oleg</code>"
            )
            return
        token, label = await _casino_parse_bet(bet_raw, balance, market, user.id)
        if token is None:
            await message.answer(label)
            return
        text, keyboard = render.render_dice_choices(game, label, token)
        await message.answer(text, reply_markup=keyboard)
        return

    token, label = await _casino_parse_bet(parts[0], balance, market, user.id)
    if token is None:
        await message.answer(label)
        return
    text, keyboard = render.render_casino_colors(label, token)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("cg:"))
async def cb_dice(
    callback: CallbackQuery, db: Database, market: MarketRepo, bot: Bot
) -> None:
    """Быстрая игра: кидаем анимированный кубик и считаем результат."""
    assert callback.data is not None
    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer("Не понял ставку", show_alert=True)
        return
    game = parts[1]
    choice = parts[-1]
    token = ":".join(parts[2:-1])
    if game not in dice_casino.GAMES or not dice_casino.is_choice_valid(game, choice):
        await callback.answer("Не понял выбор", show_alert=True)
        return

    user_id = callback.from_user.id
    unit: dict | None = None
    bet_points: int | None = None
    if token.startswith("p:"):
        try:
            bet_points = int(token[2:])
        except ValueError:
            await callback.answer("Не понял ставку", show_alert=True)
            return
        if not casino.MIN_BET <= bet_points <= casino.MAX_BET:
            await callback.answer(
                f"⚠️ Ставка от {casino.MIN_BET} до {casino.MAX_BET} очков.",
                show_alert=True,
            )
            return
        balance = await market.balance(user_id)
        if balance < bet_points:
            await callback.answer(
                f"⚠️ Не хватает очков: ставишь {bet_points}, у тебя {balance}.",
                show_alert=True,
            )
            return
    else:
        parsed = parse_handle(token[2:])
        if parsed is None:
            await callback.answer("Не понял, какую карту ставим.", show_alert=True)
            return
        try:
            unit = await market.owned_unit(user_id, parsed)
        except MarketError as error:
            await callback.answer(str(error), show_alert=True)
            return
        if unit.get("kind") == "case":
            await callback.answer("⚠️ Кейс нельзя поставить в казино.", show_alert=True)
            return

    left = await db.claim_casino(user_id, roulette_day_key(), casino.SPINS_PER_DAY)
    if left is None:
        await callback.answer(
            "🎰 Крутки на сегодня кончились. Докупка — 2 000 очков.", show_alert=True
        )
        return

    # В форум-группе кубик надо слать в тот же топик, где играют, иначе он
    # улетает в «General». message_thread_id у обычных сообщений = id топика.
    thread_id = getattr(callback.message, "message_thread_id", None)
    try:
        dice = await bot.send_dice(
            chat_id=callback.message.chat.id,
            emoji=dice_casino.emoji(game),
            message_thread_id=thread_id,
        )
        value = int(dice.dice.value)
    except Exception:  # noqa: BLE001
        log.exception("Не удалось кинуть кубик")
        await callback.answer("Кубик не долетел, попробуй ещё", show_alert=True)
        return

    # Даём анимации Телеграма проиграться: число уже есть, но игрок должен
    # увидеть, как падает кубик, а не мгновенный текст.
    if dice_casino.DICE_PAUSE_SECONDS:
        await asyncio.sleep(dice_casino.DICE_PAUSE_SECONDS)

    won = dice_casino.is_win(game, choice, value)
    mult = dice_casino.multiplier(game, choice)
    repo = CasinoRepo(db, market)
    try:
        if bet_points is not None:
            result = await repo.play_points(user_id, bet_points, won, mult, game, choice, value)
        else:
            assert unit is not None
            result = await repo.play_card(user_id, unit, won, mult, game, choice, value)
    except (CasinoError, MarketError) as error:
        await callback.answer(str(error), show_alert=True)
        return

    balance = await market.balance(user_id)
    text, keyboard = render.render_dice_result(result, balance)
    await _safe_edit(callback, text, keyboard)
    await callback.answer("Победа!" if won else "Проигрыш")


@router.callback_query(F.data.startswith("cs:"))
async def cb_casino(callback: CallbackQuery, db: Database, market: MarketRepo) -> None:
    assert callback.data is not None
    parsed_bet = casino.parse_bet_callback(callback.data)
    if parsed_bet is None:
        await callback.answer("Не понял ставку", show_alert=True)
        return
    token, color = parsed_bet
    if color not in casino.COLORS:
        await callback.answer("Неизвестный цвет", show_alert=True)
        return

    user_id = callback.from_user.id

    # Сначала проверяем ставку, и только потом тратим крутку: иначе из-за
    # опечатки в ставке или уже проданной карты день пропадал впустую.
    unit: dict | None = None
    bet_points: int | None = None
    if token.startswith("p:"):
        try:
            bet_points = int(token[2:])
        except ValueError:
            await callback.answer("Не понял ставку", show_alert=True)
            return
        if not casino.MIN_BET <= bet_points <= casino.MAX_BET:
            await callback.answer(
                f"⚠️ Ставка от {casino.MIN_BET} до {casino.MAX_BET} очков.",
                show_alert=True,
            )
            return
        balance = await market.balance(user_id)
        if balance < bet_points:
            await callback.answer(
                f"⚠️ Не хватает очков: ставишь {bet_points}, у тебя {balance}.",
                show_alert=True,
            )
            return
    else:
        parsed = parse_handle(token[2:])
        if parsed is None:
            await callback.answer("Не понял, какую карту ставим.", show_alert=True)
            return
        try:
            unit = await market.owned_unit(user_id, parsed)
        except MarketError as error:
            await callback.answer(str(error), show_alert=True)
            return
        if unit.get("kind") == "case":
            await callback.answer("⚠️ Кейс нельзя поставить в казино.", show_alert=True)
            return

    left = await db.claim_casino(user_id, roulette_day_key(), casino.SPINS_PER_DAY)
    if left is None:
        await callback.answer(
            "🎰 Крутки на сегодня кончились. Докупка — 2 000 очков.", show_alert=True
        )
        return
    repo = CasinoRepo(db, market)
    try:
        if bet_points is not None:
            result = await repo.bet_points(user_id, bet_points, color)
        else:
            assert unit is not None
            result = await repo.bet_card(user_id, unit, color)
    except (CasinoError, MarketError) as error:
        await callback.answer(str(error), show_alert=True)
        return

    balance = await market.balance(user_id)
    text, keyboard = render.render_casino_result(result, balance)
    await _safe_edit(callback, text, keyboard)
    await callback.answer("Победа!" if result["won"] else "Проигрыш")


@router.callback_query(F.data.startswith("csb:"))
async def cb_casino_buyback(
    callback: CallbackQuery, db: Database, market: MarketRepo
) -> None:
    assert callback.data is not None
    offer_id = int(callback.data.split(":", 1)[1])
    repo = CasinoRepo(db, market)
    try:
        bought = await repo.buyback(callback.from_user.id, offer_id)
    except CasinoError as error:
        await callback.answer(str(error), show_alert=True)
        return
    text = render.render_casino_bought(
        bought["card"], bought["price"], bought["balance"], bought["inventory_id"]
    )
    await _safe_edit(callback, text, None)
    await callback.answer("Карта вернулась")


# --------------------------------------------------------------------------- #
# Командный PvP
# --------------------------------------------------------------------------- #

TEAM_PVP_PREFIX = re.compile(r"(?i)^/?\s*пвп\s+")


def _first_enemy(state: dict[str, Any], unit_key: str) -> str | None:
    actor = state["sides"][unit_key]
    foe_team = team_battle.enemy_team(actor["team"])
    for key in state["teams"].get(foe_team, []):
        if state["sides"][key]["hp"] > 0:
            return key
    return None


@router.message(F.text.regexp(r"(?i)^/?\s*пвп\s+"))
async def cmd_team_pvp(
    message: Message, bot: Bot, db: Database, market: MarketRepo
) -> None:
    user = message.from_user
    if user is None or not message.text:
        return
    await db.ensure_player(user.id, user.username, user.first_name)

    body = TEAM_PVP_PREFIX.sub("", message.text).strip()
    cards_per_player = 2
    named: list[str] = []
    for token in body.split():
        if token.isdigit():
            cards_per_player = int(token)
        else:
            named.append(token)

    if named:
        if len(named) != 4:
            await message.answer(
                "⚔️ Для боя 2 на 2 перечисли всех четырёх: "
                "<code>пвп @я @союзник @враг1 @враг2</code>"
            )
            return
        people = []
        for token in named:
            row = await market.find_by_username(token)
            if row is None:
                await message.answer(f"⚠️ Не нашёл игрока {render.esc(token)}.")
                return
            people.append(
                {"user_id": int(row["user_id"]), "name": row["first_name"] or token}
            )
        if user.id not in [person["user_id"] for person in people]:
            await message.answer("⚠️ Тебя нет среди участников — так бой не начнётся.")
            return
        cards_per_player = 2 if cards_per_player not in (2, 3) else cards_per_player
    else:
        replied = message.reply_to_message
        if replied is None or replied.from_user is None:
            await message.answer(
                "⚔️ Ответь этой командой на сообщение соперника "
                "(например <code>пвп 2</code>), либо перечисли 4 юзернейма."
            )
            return
        opponent = replied.from_user
        if opponent.id == user.id or opponent.is_bot:
            await message.answer("⚔️ Нужен живой соперник.")
            return
        await db.ensure_player(opponent.id, opponent.username, opponent.first_name)
        people = [
            {"user_id": user.id, "name": user.first_name or "Игрок"},
            {
                "user_id": opponent.id,
                "name": opponent.first_name or opponent.username or "Игрок",
            },
        ]

    service = TeamBattleService(bot, db, market)
    try:
        await service.create(message.chat.id, user.id, people, cards_per_player)
    except TeamBattleError as error:
        await message.answer(f"⚠️ {error}")
        return
    await message.answer(
        "⚔️ <b>Командный бой создан!</b>\nКаждый участник выбирает карты в личке с ботом."
    )


@router.callback_query(F.data.startswith("tk:"))
async def cb_team_pick(
    callback: CallbackQuery, bot: Bot, db: Database, market: MarketRepo
) -> None:
    assert callback.data is not None
    _, battle_id, handle = callback.data.split(":", 2)
    service = TeamBattleService(bot, db, market)
    try:
        await service.toggle_card(callback, battle_id, handle)
    except TeamBattleError as error:
        await callback.answer(str(error), show_alert=True)
        return
    await callback.answer("Карта принята")


@router.callback_query(F.data.startswith("tb:"))
async def cb_team_battle(
    callback: CallbackQuery, bot: Bot, db: Database, market: MarketRepo
) -> None:
    assert callback.data is not None
    parts = callback.data.split(":")
    battle_id, step = parts[1], parts[2]
    service = TeamBattleService(bot, db, market)
    battle = await db.get_battle(battle_id)
    if battle is None:
        await callback.answer("Бой не найден", show_alert=True)
        return
    state = battle["state"]

    if state.get("over"):
        await callback.answer("Бой уже закончен.", show_alert=True)
        return

    # Кнопки принадлежат тому, чей сейчас ход: чужой тап не должен даже
    # открывать меню чужой карты.
    if step in ("u", "a", "t", "y"):
        actor = state.get("sides", {}).get(parts[3])
        if actor is None:
            await callback.answer("Карта не найдена", show_alert=True)
            return
        if actor["user_id"] != callback.from_user.id:
            await callback.answer("Это не твоя карта.", show_alert=True)
            return
        if state.get("turn") != callback.from_user.id:
            await callback.answer("Сейчас не твой ход.", show_alert=True)
            return

    try:
        if step == "c":
            text, keyboard = render.render_team_battle(battle, state)
            await _safe_edit(callback, text, keyboard)
        elif step == "u":
            unit_key = parts[3]
            text, keyboard = render.render_team_battle(
                battle, state, {"unit": unit_key}
            )
            await _safe_edit(callback, text, keyboard)
        elif step == "a":
            unit_key, action = parts[3], parts[4]
            text, keyboard = render.render_team_battle(
                battle, state, {"unit": unit_key, "action": action}
            )
            await _safe_edit(callback, text, keyboard)
        elif step == "t":
            unit_key, action, target = parts[3], parts[4], parts[5]
            card = get_card(state["sides"][unit_key]["card_id"])
            need = ability_targets(card) if action == "ability" else "enemy"
            if need == "both":
                text, keyboard = render.render_team_battle(
                    battle, state, {"unit": unit_key, "action": action, "target": target}
                )
                await _safe_edit(callback, text, keyboard)
            elif need == "ally":
                await service.act(
                    callback, battle_id, unit_key, action, _first_enemy(state, unit_key), target
                )
            else:
                await service.act(callback, battle_id, unit_key, action, target, None)
        elif step == "y":
            unit_key, target, ally = parts[3], parts[4], parts[5]
            await service.act(callback, battle_id, unit_key, "ability", target, ally)
        else:
            await callback.answer("Не понял шаг", show_alert=True)
            return
    except TeamBattleError as error:
        await callback.answer(str(error), show_alert=True)
        return
    await callback.answer()


# --------------------------------------------------------------------------- #
# FAQ
# --------------------------------------------------------------------------- #


@router.message(Command("faq"))
@router.message(NormalizedText("faq", "фак", "частые вопросы"))
async def cmd_faq(message: Message) -> None:
    text, keyboard = render.faq_menu()
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("fq:"))
async def cb_faq(callback: CallbackQuery) -> None:
    assert callback.data is not None
    parts = callback.data.split(":")
    kind = parts[1] if len(parts) > 1 else "menu"

    if kind == "menu":
        text, keyboard = render.faq_menu()
    elif kind == "cards":
        text, keyboard = render.faq_cards(int(parts[2]) if len(parts) > 2 else 0)
    elif kind == "card":
        try:
            card = get_card(parts[2])
        except Exception:  # noqa: BLE001
            await callback.answer("Такой карты нет", show_alert=True)
            return
        text, keyboard = render.faq_card(card)
        await _card_page(callback, card, text, keyboard)
        await callback.answer()
        return
    elif kind == "drop":
        text, keyboard = render.faq_drops()
    elif kind == "items":
        text, keyboard = render.faq_items(parts[2] if len(parts) > 2 else "aura")
    elif kind == "price":
        text, keyboard = render.faq_price()
    else:
        await callback.answer("Не понял", show_alert=True)
        return

    await _safe_edit(callback, text, keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("ts:"))
async def cb_team_stop(
    callback: CallbackQuery, bot: Bot, db: Database, market: MarketRepo
) -> None:
    """Кнопка «Остановить бой» — доступна любому участнику."""
    assert callback.data is not None
    battle_id = callback.data.split(":", 1)[1]
    service = TeamBattleService(bot, db, market)
    try:
        await service.stop(battle_id, callback.from_user.id)
    except TeamBattleError as error:
        await callback.answer(str(error), show_alert=True)
        return
    await callback.answer("Бой остановлен")


@router.message(Command("stop", "стоп"))
@router.message(NormalizedText("стоп", "stop", "остановить бой"))
async def cmd_team_stop(
    message: Message, bot: Bot, db: Database, market: MarketRepo
) -> None:
    """Текстом: останавливает все твои активные командные бои."""
    user = message.from_user
    if user is None:
        return
    battles = await db.find_active_team_battles(user.id)
    if not battles:
        await message.answer("У тебя нет активных командных боёв.")
        return
    service = TeamBattleService(bot, db, market)
    stopped = 0
    for battle in battles:
        try:
            await service.stop(battle["battle_id"], user.id)
            stopped += 1
        except TeamBattleError:
            continue
    await message.answer(f"🛑 Остановлено боёв: <b>{stopped}</b>.")


# --------------------------------------------------------------------------- #
# Магазин (Telegram Mini App)
# --------------------------------------------------------------------------- #


def _base_url() -> str:
    # settings.public_url уже нормализован (добавляет схему, если её нет).
    return (settings.public_url or "").rstrip("/")


def _app_url() -> str:
    base = _base_url()
    return f"{base}/app" if base else ""


@router.message(Command("shop", "магазин"))
@router.message(NormalizedText("магазин", "шоп", "shop"))
async def cmd_shop(message: Message) -> None:
    user = message.from_user
    if user is None:
        return
    url = _app_url()
    if not url:
        await message.answer("⚠️ Магазин не настроен: нет PUBLIC_URL.")
        return
    if message.chat.type != "private":
        await message.answer(
            "🍁 Магазин открывается только в личке со мной — "
            "напиши мне туда, там кнопка снизу."
        )
        return

    from aiogram.types import WebAppInfo

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🍁 Открыть магазин", web_app=WebAppInfo(url=url))]
        ]
    )
    await message.answer(
        "🍁 <b>Магазин «Северо-Юг»</b>\n\n"
        "🟤 Учителя · 🎁 Наборы · ❤️ Аксессуары\n"
        "Открывай кнопкой — или жми «Магазин» рядом с полем ввода.",
        reply_markup=keyboard,
    )


@router.message(Command("stocks", "exchange"))
@router.message(NormalizedText("биржа", "акции", "биржа акций"))
async def cmd_stocks(message: Message) -> None:
    """Биржа — отдельной мини-аппкой, как магазин."""
    user = message.from_user
    if user is None:
        return
    base = _base_url()
    if not base:
        await message.answer("⚠️ Биржа не настроена: нет PUBLIC_URL.")
        return
    if message.chat.type != "private":
        await message.answer(
            "📈 Биржа открывается только в личке со мной — напиши мне туда."
        )
        return

    from aiogram.types import WebAppInfo

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📈 Открыть биржу", web_app=WebAppInfo(url=f"{base}/stocks")
                )
            ]
        ]
    )
    await message.answer(
        "📈 <b>Биржа «Северо-Юг»</b>\n\n"
        "Курсы двигаются каждые 15 секунд: 🟩 вверх, 🟥 вниз.\n"
        "Покупай дешевле — продавай дороже. Быстрым трейдом не нафармишь: "
        "комиссия на вход и на выход.",
        reply_markup=keyboard,
    )


@router.message(Command("fav", "favorite"))
@router.message(NormalizedText("любимая", "любимая карта", "фаворит"))
async def cmd_favorite(message: Message, db: Database, market: MarketRepo) -> None:
    """Любимая карта: показать или выбрать вручную."""
    user = message.from_user
    if user is None:
        return
    await db.ensure_player(user.id, user.username, user.first_name)
    parts = (message.text or "").split()[1:]
    if not parts:
        profile = await db.player_profile(user.id)
        fav_id = profile.get("favorite_card_id") if profile else None
        card = CARDS_BY_ID.get(fav_id) if fav_id else None
        if card is not None:
            await message.answer(
                f"❤️ Любимая карта: {card.rarity_emoji} "
                f"<b>{render.esc(card.display_name)}</b>\n\n"
                "Поменять: <code>/fav #oleg</code> или <code>/fav #12</code>."
            )
        else:
            await message.answer(
                "❤️ Любимая карта пока не выбрана.\n"
                "Укажи: <code>/fav #oleg</code> или <code>/fav #12</code>."
            )
        return
    parsed = parse_handle(parts[0])
    if parsed is None:
        await message.answer("Формат: <code>/fav #oleg</code> или <code>/fav #12</code>")
        return
    try:
        unit = await market.owned_unit(user.id, parsed)
    except MarketError as error:
        await message.answer(f"⚠️ {error}")
        return
    if unit.get("kind") == "case":
        await message.answer("Кейс не может быть любимой картой.")
        return
    card = get_card(unit["card_id"])
    await db.set_favorite_card(user.id, card.card_id)
    await message.answer(
        f"❤️ Любимая карта: {card.rarity_emoji} <b>{render.esc(card.display_name)}</b>\n"
        "Она теперь показывается в профиле — /profile"
    )


# --------------------------------------------------------------------------- #
# Рейд-босс: тыкают все, карты не нужны
# --------------------------------------------------------------------------- #


async def _boss_view(repo: BossRepo, raid: dict) -> tuple[str, Any]:
    stats = await repo.stats(raid["id"])
    top = await repo.top(raid["id"], 5)
    return render.render_boss(raid, top, stats)


async def broadcast_boss(
    bot: Bot, db: Database, repo: BossRepo, raid: dict, exclude: int | None = None
) -> int:
    """Рассылает карточку босса во все группы, чтобы каждый мог бить."""
    text, keyboard = await _boss_view(repo, raid)
    sent = 0
    for chat_id in await db.broadcast_targets():
        if exclude is not None and int(chat_id) == int(exclude):
            continue
        try:
            await bot.send_message(chat_id, text, reply_markup=keyboard)
        except Exception:  # noqa: BLE001
            continue
        sent += 1
        await asyncio.sleep(0.05)
    return sent


@router.message(Command("boss", "босс"))
@router.message(NormalizedText("босс", "рейд"))
async def cmd_boss(message: Message, boss_repo: BossRepo) -> None:
    """Показать текущего босса, если рейд идёт."""
    raid = await boss_repo.active()
    if raid is None:
        await message.answer("Сейчас рейда нет. Запустят — сразу увидишь карточку.")
        return
    text, keyboard = await _boss_view(boss_repo, raid)
    await message.answer(text, reply_markup=keyboard)


async def _finish_raid(
    bot: Bot, db: Database, repo: BossRepo, raid: dict
) -> None:
    """Босса добили: награда всем и анонс в группы и лички."""
    if not await repo.mark_rewarded(raid["id"]):
        return
    stats = await repo.stats(raid["id"])
    top = await repo.top(raid["id"], 10)
    try:
        await db.grant_boss_rewards(
            day_key(),
            roulette_day_key(),
            boss.REWARD_DROPS,
            boss.REWARD_SPINS,
            boss.REWARD_CASES,
        )
    except Exception:  # noqa: BLE001
        log.exception("Рейд: не смог выдать награды")
    text = render.render_boss_victory(raid, top, stats)
    for chat_id in await db.broadcast_targets():
        try:
            await bot.send_message(chat_id, text)
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(0.05)
    for user_id in await db.all_player_ids():
        try:
            await bot.send_message(user_id, text)
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(0.05)


@router.callback_query(F.data == "boss:hit")
async def cb_boss(
    callback: CallbackQuery, bot: Bot, db: Database, boss_repo: BossRepo
) -> None:
    """Удар по боссу: один тап — 50 урона, карты не нужны."""
    user = callback.from_user
    raid = await boss_repo.active()
    if raid is None:
        await callback.answer("Босса уже добили — жди следующего рейда.", show_alert=True)
        return
    try:
        result = await boss_repo.hit(
            raid["id"], user.id, datetime.now(timezone.utc)
        )
    except BossError as error:
        await callback.answer(str(error), show_alert=True)
        return
    if result.get("cooldown"):
        await callback.answer("Не так быстро — дай и другим ударить 🙂")
        return
    mine = await boss_repo.my_hits(raid["id"], user.id)
    if result["dead"]:
        await callback.answer(
            f"💥 Добил! Урон {result['damage']}", show_alert=True
        )
    else:
        await callback.answer(
            f"👊 −{result['damage']} HP · твой вклад: {mine['hits']}"
        )
    fresh = await boss_repo.get(raid["id"]) or raid
    text, keyboard = await _boss_view(boss_repo, fresh)
    if callback.message is not None:
        try:
            await callback.message.edit_text(text, reply_markup=keyboard)
        except TelegramBadRequest as error:
            if "not modified" not in str(error).lower():
                log.warning("Рейд-босс не обновился: %s", error)
    if result["dead"]:
        await _finish_raid(bot, db, boss_repo, fresh)


# --------------------------------------------------------------------------- #
# /my — коллекция по страницам
# --------------------------------------------------------------------------- #


async def _my_home_text(db: Database, market: MarketRepo, user_id: int):
    stats = await db.collection_stats(user_id)
    _, units = await collection_data(db, market, user_id)
    upgraded = sum(1 for unit in units if unit.get("inventory_id"))
    cases = len(await db.user_cases(user_id))
    return render.my_home(stats, len(CARDS), upgraded, cases)


async def _my_unit(db: Database, market: MarketRepo, user_id: int, handle: str):
    _, units = await collection_data(db, market, user_id)
    return next((unit for unit in units if unit["handle"] == handle), None)


async def _card_page(
    callback: CallbackQuery, card: Any, text: str, keyboard: Any
) -> None:
    """Показывает карту с артом. Не вышло — обычным текстом."""
    url = image_url(card.card_id, _base_url())
    if url and callback.message is not None:
        try:
            await callback.bot.send_photo(
                chat_id=callback.message.chat.id,
                message_thread_id=getattr(callback.message, "message_thread_id", None),
                photo=url,
                caption=text,
                reply_markup=keyboard,
            )
        except Exception:  # noqa: BLE001
            log.warning("Арт %s не отправился", url)
        else:
            try:
                await callback.message.delete()
            except Exception:  # noqa: BLE001
                pass
            return
    # Арта нет — показываем карточку текстом. Без этой строки карты без
    # картинки вообще не открывались (кнопка молчала).
    await _safe_edit(callback, text, keyboard)


async def _profile_photo(bot: Bot, user_id: int) -> str | None:
    """Аватарка игрока, если Телеграм её отдаёт."""
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
    except Exception:  # noqa: BLE001
        return None
    if photos is None or not getattr(photos, "photos", None):
        return None
    return photos.photos[0][-1].file_id


async def _send_profile(
    message: Message, bot: Bot, user_id: int, text: str, keyboard
) -> None:
    """Профиль: аватарка — отдельным сообщением, текст и кнопки — своим.

    Так кнопка «Мои карты» не лежит поверх фото.
    """
    photo = await _profile_photo(bot, user_id)
    if photo:
        with contextlib.suppress(Exception):
            await message.answer_photo(photo)
    await message.answer(text, reply_markup=keyboard)


async def _edit_profile(
    callback: CallbackQuery, bot: Bot, user_id: int, text: str, keyboard
) -> None:
    """Профиль по кнопке: старый экран убираем, аватарку шлём отдельно."""
    message = callback.message
    if message is None:
        return
    photo = await _profile_photo(bot, user_id)
    with contextlib.suppress(Exception):
        await message.delete()
    if photo:
        with contextlib.suppress(Exception):
            await callback.bot.send_photo(
                chat_id=message.chat.id,
                message_thread_id=getattr(message, "message_thread_id", None),
                photo=photo,
            )
    with contextlib.suppress(Exception):
        await callback.bot.send_message(
            chat_id=message.chat.id,
            message_thread_id=getattr(message, "message_thread_id", None),
            text=text,
            reply_markup=keyboard,
        )


@router.callback_query(F.data.startswith("my:"))
async def cb_my(
    callback: CallbackQuery, db: Database, market: MarketRepo, bot: Bot
) -> None:
    assert callback.data is not None
    user_id = callback.from_user.id
    parts = callback.data.split(":", 3)
    action = parts[1] if len(parts) > 1 else "home"

    if action == "home":
        text, keyboard = await _my_home_text(db, market, user_id)
        await _safe_edit(callback, text, keyboard)
    elif action == "c":
        counts = await db.get_collection(user_id)
        text, keyboard = render.my_cards(
            cards_sorted_for_user(list(counts)),
            counts,
            int(parts[2]) if len(parts) > 2 else 0,
        )
        await _safe_edit(callback, text, keyboard)
    elif action == "u":
        _, units = await collection_data(db, market, user_id)
        upgraded = [unit for unit in units if unit.get("inventory_id")]
        text, keyboard = render.my_units(
            upgraded, int(parts[2]) if len(parts) > 2 else 0
        )
        await _safe_edit(callback, text, keyboard)
    elif action == "k":
        cases = await db.user_cases(user_id)
        lines = ["📦 <b>Кейсы</b>", ""]
        if cases:
            lines += [
                f"      <code>#c{case['id']}</code> закрытый кейс" for case in cases
            ]
            lines += ["", "Открыть: /case"]
        else:
            lines.append("Пусто. Крути рулетку: /roulette")
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="my:home")]
            ]
        )
        await _safe_edit(callback, "\n".join(lines), keyboard)
    elif action == "p":
        profile = await db.player_profile(user_id)
        await _edit_profile(
            callback,
            bot,
            user_id,
            render.render_profile(profile, len(CARDS)),
            render.profile_keyboard(user_id, is_owner=True),
        )
    elif action in ("d", "i", "a") and len(parts) > 2:
        handle = parts[2]
        unit = await _my_unit(db, market, user_id, handle)
        if unit is None:
            await callback.answer("Карта не найдена", show_alert=True)
            return
        card_id = unit["card"].card_id
        owned = await db.my_accessories(user_id)

        if action == "a":
            acc_id = int(parts[3]) if len(parts) > 3 else 0
            acc = next((item for item in owned if item["id"] == acc_id), None)
            if acc is None:
                await callback.answer("Аксессуар не найден", show_alert=True)
                return
            if acc.get("card_id") == card_id:
                await db.detach_accessory(user_id, acc_id)
                await callback.answer(f"{acc['name']} снят")
            else:
                await db.attach_accessory(user_id, acc_id, card_id)
                await callback.answer(f"{acc['name']} → {unit['card'].name}")
            owned = await db.my_accessories(user_id)
            unit = await _my_unit(db, market, user_id, handle) or unit
            action = "i"

        if action == "i":
            text, keyboard = render.my_items(unit, owned)
            await _safe_edit(callback, text, keyboard)
            await callback.answer()
            return

        worn = [item for item in owned if item.get("card_id") == card_id]
        text, keyboard = render.my_card(unit, worn)
        await _card_page(callback, unit["card"], text, keyboard)
        await callback.answer()
        return
    elif action == "v" and len(parts) > 2:
        handle = parts[2]
        unit = await _my_unit(db, market, user_id, handle)
        if unit is None:
            await callback.answer("Карта не найдена", show_alert=True)
            return
        card = unit["card"]
        await db.set_favorite_card(user_id, card.card_id)
        owned = await db.my_accessories(user_id)
        worn = [item for item in owned if item.get("card_id") == card.card_id]
        text, keyboard = render.my_card(unit, worn)
        await _safe_edit(callback, text, keyboard)
        await callback.answer(f"❤️ Любимая: {card.name}")
        return
    else:
        await callback.answer()
        return
    await callback.answer()



# --------------------------------------------------------------------------- #
# Промокоды и главное меню
# --------------------------------------------------------------------------- #


def _start_payload(message: Message) -> str:
    """Аргумент deep-link: /start ref_abc -> 'ref_abc'."""
    parts = (message.text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


@router.message(CommandStart())
async def cmd_start_menu(message: Message, bot: Bot, db: Database) -> None:
    user = message.from_user
    payload = _start_payload(message)
    if user is not None and payload:
        await db.ensure_player(user.id, user.username, user.first_name)
        note = None
        try:
            note = await referrals.redeem(db, bot, user.id, payload)
        except Exception:  # noqa: BLE001 - меню должно показаться в любом случае
            log.exception("Реферальный переход не обработался")
        if note:
            await message.answer(note)

    # Ссылки из групп: ?start=caseapp / ?start=rouletteapp открывают мини-аппку.
    if user is not None and payload in ("caseapp", "rouletteapp"):
        await db.ensure_player(user.id, user.username, user.first_name)
        await _send_miniapp(
            message, bot, "case" if payload == "caseapp" else "roulette"
        )
        return

    # Кнопки-мини-апп Telegram разрешает только в личке: в группе /start
    # должен отдать то же меню, но без web_app-кнопок.
    app_url = _base_url() if message.chat.type == "private" else ""
    text, keyboard = render.render_main_menu(await _bot_username(bot), app_url)
    await message.answer(text, reply_markup=keyboard)
    # Заодно подсказка про рефералку — но только в личке, чтобы не сорить в группах.
    if message.chat.type == "private":
        await message.answer(
            "🔗 Приведи друга и получи попытку «Северо-Юг»: /ref"
        )


@router.message(Command("promo", "промокод"))
@router.message(NormalizedText("промокод", "промо"))
async def cmd_promo(message: Message, db: Database) -> None:
    user = message.from_user
    if user is None:
        return
    await db.ensure_player(user.id, user.username, user.first_name)
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer(
            "🎁 Формат: <code>/promo КОД</code>\n"
            "Коды раздаю в чате — следи за анонсами."
        )
        return
    try:
        # Код может состоять из нескольких слов («северо юн»).
        await message.answer(await promo.redeem(db, user.id, " ".join(parts[1:])))
    except PromoError as error:
        await message.answer(str(error))


@router.message(Command("ref", "referral", "рефералка"))
@router.message(NormalizedText("реф", "рефералка", "моя ссылка"))
async def cmd_ref(message: Message, db: Database, bot: Bot) -> None:
    """Личная реферальная ссылка: +1 попытка «Северо-Юг» за друга."""
    user = message.from_user
    if user is None:
        return
    await db.ensure_player(user.id, user.username, user.first_name)
    try:
        text = await referrals.status(db, user.id, await _bot_username(bot))
    except ReferralError as error:
        await message.answer(f"⚠️ {error}")
        return
    await message.answer(text)


@router.callback_query(F.data.startswith("mn:"))
async def cb_menu(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    assert callback.data is not None
    action = callback.data.split(":", 1)[1]
    if action == "top":
        await _safe_edit(callback, render.render_top(await db.top_players(10)), None)
    elif action == "help":
        await _safe_edit(callback, render.render_help(await _bot_username(bot)), None)
    else:
        await callback.answer()
        return
    await callback.answer()


@router.callback_query(F.data == "cspin")
async def cb_extra_spin(
    callback: CallbackQuery, db: Database, market: MarketRepo
) -> None:
    """Докупка одной крутки казино за 2000 очков."""
    user_id = callback.from_user.id
    left = await db.buy_casino_spin(
        user_id, roulette_day_key(), casino.EXTRA_SPIN_PRICE, casino.SPINS_PER_DAY
    )
    if left is None:
        balance = await market.balance(user_id)
        await callback.answer(
            f"Крутка стоит {casino.EXTRA_SPIN_PRICE}, у тебя {balance}.",
            show_alert=True,
        )
        return
    await callback.answer(
        f"🎰 Крутка куплена! Осталось на сегодня: {left}. "
        f"Очков: {await market.balance(user_id)}"
    )



# --------------------------------------------------------------------------- #
# Кликер-копилка
# --------------------------------------------------------------------------- #


_KOPILKA_TAPS: dict[int, float] = {}
# Сколько секунд между перерисовками HUD: три человека, тапающие одно сообщение,
# иначе упираются во флуд-лимит Telegram.
KOPILKA_REDRAW_SECONDS = 2.5
_KOPILKA_REDRAW: dict[int, float] = {}


# Сколько секунд между перерисовками HUD. Иначе три человека, тапающие одно
# сообщение, упираются во флуд-лимит Telegram.
KOPILKA_REDRAW_SECONDS = 2.5

_KOPILKA_STATE: dict[str, tuple[float, object]] = {}


async def _clicker_state(db: Database):
    """Состояние ивента с кешем на 2 секунды — не дёргаем базу на каждый тап."""
    cached = _KOPILKA_STATE.get("state")
    moment = time.monotonic()
    if cached is not None and moment - cached[0] < 2.0:
        return cached[1]
    state = await event.state(db)
    _KOPILKA_STATE["state"] = (moment, state)
    return state


async def _clicker_view(db: Database, user_id: int, running: bool, last: str = ""):
    me = await db.kopilka_me(user_id)
    common = await db.kopilka_common()
    top = await db.kopilka_top(5)
    return render.clicker_hud(me, common, top, running, last)


@router.message(Command("kopilka", "копилка"))
@router.message(NormalizedText("копилка", "кликер"))
async def cmd_kopilka(message: Message, db: Database) -> None:
    user = message.from_user
    if user is None:
        return
    await db.ensure_player(user.id, user.username, user.first_name)
    state = await event.state(db)
    if not state.clicker:
        await message.answer(
            "🎮 Кликер сейчас выключен. Его включает админ командой /admin kopilka."
        )
        return
    text, keyboard = await _clicker_view(db, user.id, state.active)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("kl:"))
async def cb_kopilka(callback: CallbackQuery, db: Database) -> None:
    assert callback.data is not None
    action = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    state = await _clicker_state(db)
    if not state.clicker:
        await callback.answer("Кликер выключен", show_alert=True)
        return
    last = ""
    if action == "c":
        moment = time.monotonic()
        if moment - _KOPILKA_TAPS.get(user_id, 0.0) < kopilka.TAP_COOLDOWN_SECONDS:
            await callback.answer("Слишком быстро 🐢")
            return
        _KOPILKA_TAPS[user_id] = moment

        kind, value = kopilka.roll()
        try:
            await db.kopilka_tap(
                user_id,
                points=int(value) if kind == kopilka.POINTS else 0,
                drops=1 if kind == kopilka.DROP else 0,
                spins=1 if kind == kopilka.SPIN else 0,
                cases=1 if kind == kopilka.CASE else 0,
                cards=[value.card_id] if kind == kopilka.CARD else None,
            )
        except Exception:  # noqa: BLE001
            log.exception("копилка: тап не записался")
            await callback.answer("Заминка, стукни ещё раз")
            return

        # Награду показываем тостиком — ради этого сообщение править не нужно.
        await callback.answer(kopilka.label(kind, value))

        chat_id = callback.message.chat.id if callback.message else user_id
        if moment - _KOPILKA_REDRAW.get(chat_id, 0.0) < KOPILKA_REDRAW_SECONDS:
            return
        _KOPILKA_REDRAW[chat_id] = moment
    else:
        await callback.answer()

    try:
        text, keyboard = await _clicker_view(db, user_id, state.active, last)
        await _safe_edit(callback, text, keyboard)
    except TelegramRetryAfter as error:
        log.warning("кликер: Telegram просит подождать %.1f сек", error.retry_after)
    except Exception:  # noqa: BLE001
        log.exception("кликер: не смог перерисовать HUD")



# --------------------------------------------------------------------------- #
# Апгрейдер карт
# --------------------------------------------------------------------------- #


@router.message(Command("upgrader", "апгрейдер"))
@router.message(NormalizedText("апгрейдер", "апгрейд"))
async def cmd_upgrader(message: Message) -> None:
    base = _base_url()
    if not base:
        await message.answer("⚠️ Апгрейдер не настроен: нет PUBLIC_URL.")
        return
    if message.chat.type != "private":
        await message.answer(
            "♻️ Апгрейдер открывается в личке со мной — там кнопка.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="♻️ Открыть бота",
                            url=f"https://t.me/{await _bot_username(message.bot)}",
                        )
                    ]
                ]
            ),
        )
        return
    from aiogram.types import WebAppInfo

    await message.answer(
        "♻️ <b>Апгрейдер карт</b>\n\n"
        "Кладёшь свою карту в первый слот, выбираешь желаемую во второй — "
        "и крутится рулетка с шансом.\n"
        "Чем жаднее апгрейд, тем он реже: с эпика на мифика ~20%, "
        "а с Олега на Леру — 0.1%.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="♻️ Открыть апгрейдер",
                        web_app=WebAppInfo(url=f"{base}/upgrader"),
                    )
                ]
            ]
        ),
    )



# --------------------------------------------------------------------------- #
# Скупщик
# --------------------------------------------------------------------------- #


@router.message(Command("buyer", "скупщик"))
@router.message(NormalizedText("скупщик", "buyer"))
async def cmd_buyer(message: Message) -> None:
    base = _base_url()
    if not base:
        await message.answer("⚠️ Скупщик не настроен: нет PUBLIC_URL.")
        return
    text = (
        "💰 <b>Скупщик</b>\n\n"
        f"{buyer.describe()}\n"
        "Любые карты — и обычные, и улучшенные. Сразу, без комиссии и без ожидания."
    )
    if message.chat.type != "private":
        await message.answer(
            text + "\n\nОткрывается в личке со мной — там кнопка.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="💰 Открыть бота",
                            url=f"https://t.me/{await _bot_username(message.bot)}",
                        )
                    ]
                ]
            ),
        )
        return
    from aiogram.types import WebAppInfo

    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💰 Открыть скупщика",
                        web_app=WebAppInfo(url=f"{base}/buyer"),
                    )
                ]
            ]
        ),
    )



# --------------------------------------------------------------------------- #
# Стили и уровни
# --------------------------------------------------------------------------- #


@router.message(Command("style", "стиль", "стили"))
@router.message(NormalizedText("стиль", "стили", "оформление"))
async def cmd_style(message: Message, db: Database) -> None:
    user = message.from_user
    if user is None:
        return
    await db.ensure_player(user.id, user.username, user.first_name)
    owned = await db.owned_themes(user.id)
    current = await db.current_theme(user.id)
    text, keyboard = render.render_themes(current, owned)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("th:"))
async def cb_theme(callback: CallbackQuery, db: Database) -> None:
    assert callback.data is not None
    user_id = callback.from_user.id
    theme_id = callback.data.split(":", 1)[1]
    theme = themes.get(theme_id)
    if theme.id != theme_id:
        await callback.answer("Такого стиля нет", show_alert=True)
        return
    owned = await db.owned_themes(user_id)
    if theme.price > 0 and theme.id not in owned:
        await callback.answer(
            f"Стиль «{theme.name}» не куплен — он в магазине (/shop)", show_alert=True
        )
        return
    await db.set_theme(user_id, theme.id)
    text, keyboard = render.render_themes(theme.id, owned)
    await _safe_edit(callback, text, keyboard)
    await callback.answer(f"Стиль «{theme.name}» включён")


@router.message(Command("levels", "уровни", "lvl", "leveltop"))
@router.message(NormalizedText("топ уровней", "топ по уровням", "уровни"))
async def cmd_levels(message: Message, db: Database) -> None:
    await message.answer(render.render_level_top(await db.level_top(10)))



# --------------------------------------------------------------------------- #
# Триггер ивента: слово «ИВЕНТ!» — только админ
# --------------------------------------------------------------------------- #


def _is_event_word(message: Message) -> bool:
    """Слово-рубильник: «ИВЕНТ!» в любом регистре."""
    return bool(message.text) and message.text.strip().upper() == "ИВЕНТ!"


@router.message(_is_event_word)
async def cmd_event_trigger(message: Message, db: Database) -> None:
    from datetime import timedelta

    from . import event_week as ev

    user = message.from_user
    if user is None or user.id not in settings.admin_ids:
        return
    state = await db.event_state()
    now = datetime.now(timezone.utc)
    if state.get("active") and not ev.is_over(state.get("ends_at"), now):
        await db.event_stop()
        await message.answer("🛑 <b>Ивент «Звёздочка» остановлен.</b>")
        return
    await db.event_start(now, now + timedelta(days=ev.DAYS), "Звёздочка")
    await message.answer(
        "🌟 <b>ИВЕНТ!</b>\n\n"
        "Звёздочка упала на школьный двор и рассыпалась на осколки.\n"
        f"У тебя <b>{ev.DAYS} дней</b>: каждый день по {ev.QUESTS_PER_DAY} квестов, "
        f"собрать нужно <b>{ev.NEED}</b>.\n\n"
        "Заходи в приложение — там кнопка «СОБЫТИЕ»."
    )



# --------------------------------------------------------------------------- #
# Награды и теги профиля — выдаёт только админ
# --------------------------------------------------------------------------- #


async def _profile_target(message: Message, market: MarketRepo, parts: list[str]):
    """Куда вешаем награду: ответ на сообщение, @ник или id."""
    reply = message.reply_to_message
    if reply is not None and reply.from_user is not None:
        return int(reply.from_user.id), reply.from_user.first_name
    if not parts:
        return None, None
    raw = parts[0].lstrip("@")
    if raw.startswith("id"):
        raw = raw[2:]
    if raw.isdigit():
        return int(raw), None
    found = await market.find_by_username("@" + raw)
    if found is None:
        return None, None
    return int(found["user_id"]), found["first_name"]


@router.message(Command("награда", "reward"))
async def cmd_reward(message: Message, db: Database, market: MarketRepo) -> None:
    user = message.from_user
    if user is None or user.id not in settings.admin_ids:
        return
    parts = (message.text or "").split(maxsplit=2)
    target_id, target_name = await _profile_target(message, market, parts[1:2])
    text = " ".join(parts[2:]).strip() if len(parts) > 2 else ""
    if target_id is None or not text:
        await message.answer(
            "Формат: <code>/reward @ник текст награды</code>\n"
            "Или ответом на сообщение: <code>/reward текст награды</code>\n"
            "Эмодзи в начале текста станет иконкой."
        )
        return
    icon = "🏆"
    first = text.split()[0] if text.split() else ""
    if first and not first[0].isalnum():
        icon, text = first, " ".join(text.split()[1:]).strip()
        if not text:
            text, icon = icon, "🏆"
    await db.ensure_player(target_id, None, target_name)
    await db.profile_reward_add(target_id, icon, text[:80])
    await message.answer(
        f"🏆 Награда «{render.esc(icon)} {render.esc(text[:80])}» выдана "
        f"<b>{render.esc(target_name or target_id)}</b>."
    )


@router.message(Command("тег", "tag"))
async def cmd_tag_cmd(message: Message, db: Database, market: MarketRepo) -> None:
    user = message.from_user
    if user is None or user.id not in settings.admin_ids:
        return
    parts = (message.text or "").split(maxsplit=2)
    target_id, target_name = await _profile_target(message, market, parts[1:2])
    tag = (parts[2] if len(parts) > 2 else "").strip().lower().lstrip("-")
    if target_id is None:
        await message.answer("Формат: <code>/tag @ник supporter</code> или ответом на сообщение")
        return
    if not tag:
        await message.answer(
            "Теги: " + ", ".join(f"<code>{key}</code> — {label}" for key, label in profiles.TAGS.items())
        )
        return
    if tag not in profiles.TAGS:
        await message.answer("Не знаю такой тег. Доступные: " + ", ".join(profiles.TAGS))
        return
    await db.ensure_player(target_id, None, target_name)
    await db.profile_tag_set(target_id, tag, True)
    await message.answer(
        f"Тег {profiles.tag_label(tag)} выдан <b>{render.esc(target_name or target_id)}</b>."
    )


@router.message(Command("снятьтег", "untag"))
async def cmd_untag(message: Message, db: Database, market: MarketRepo) -> None:
    user = message.from_user
    if user is None or user.id not in settings.admin_ids:
        return
    parts = (message.text or "").split(maxsplit=2)
    target_id, target_name = await _profile_target(message, market, parts[1:2])
    tag = (parts[2] if len(parts) > 2 else "").strip().lower()
    if target_id is None or tag not in profiles.TAGS:
        await message.answer("Формат: <code>/untag @ник supporter</code>")
        return
    await db.profile_tag_set(target_id, tag, False)
    await message.answer(f"Тег снят с <b>{render.esc(target_name or target_id)}</b>.")



# --------------------------------------------------------------------------- #
# Бан
# --------------------------------------------------------------------------- #


@router.message(Command("ban", "бан"))
async def cmd_ban(message: Message, db: Database, market: MarketRepo) -> None:
    user = message.from_user
    if user is None or user.id not in settings.admin_ids:
        return
    parts = (message.text or "").split(maxsplit=2)
    target_id, target_name = await _profile_target(message, market, parts[1:2])
    reason = " ".join(parts[2:]).strip() if len(parts) > 2 else "без причины"
    if target_id is None:
        await message.answer(
            "Формат: <code>/ban @ник причина</code>\n"
            "Или ответом на сообщение: <code>/ban причина</code>"
        )
        return
    if target_id in settings.admin_ids:
        await message.answer("Себя банить нельзя.")
        return
    await db.ensure_player(target_id, None, target_name)
    await db.set_ban(target_id, True, reason)
    await message.answer(
        f"🚫 <b>Забанен:</b> {render.esc(target_name or str(target_id))}\n"
        f"Причина: {render.esc(reason)}"
    )


@router.message(Command("unban", "разбан"))
async def cmd_unban(message: Message, db: Database, market: MarketRepo) -> None:
    user = message.from_user
    if user is None or user.id not in settings.admin_ids:
        return
    parts = (message.text or "").split(maxsplit=1)
    target_id, target_name = await _profile_target(message, market, parts[1:2])
    if target_id is None:
        await message.answer("Формат: <code>/unban @ник</code> или ответом на сообщение")
        return
    await db.set_ban(target_id, False, "")
    await message.answer(f"✅ Разбанен: <b>{render.esc(target_name or str(target_id))}</b>")


@router.message(Command("bans", "баны"))
async def cmd_bans(message: Message, db: Database) -> None:
    user = message.from_user
    if user is None or user.id not in settings.admin_ids:
        return
    async with db.pool.acquire() as con:  # type: ignore[attr-defined]
        rows = await con.fetch(
            "select user_id, first_name, username, ban_reason from players "
            "where banned = true order by banned_at desc limit 30"
        )
    if not rows:
        await message.answer("Забаненных нет.")
        return
    lines = ["🚫 <b>Забаненные</b>", ""]
    for row in rows:
        nick = f" @{row['username']}" if row["username"] else f" id{row['user_id']}"
        lines.append(
            f"· <b>{render.esc(str(row['first_name'] or '?'))}</b>{render.esc(nick)} — "
            f"{render.esc(str(row['ban_reason'] or 'без причины'))}"
        )
    await message.answer("\n".join(lines))
