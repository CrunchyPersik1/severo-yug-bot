"""Хэндлеры aiogram: выпадение карт, коллекция, лидерборд и PvP."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart, Filter
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message

from . import admin_actions, casino, render, team_battle
from .battle import ability_targets
from .battle_service import BattleError, BattleService
from .casino_repo import CasinoError, CasinoRepo
from .team_service import TeamBattleError, TeamBattleService
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from .config import settings
from .cards import CARDS, cards_sorted_for_user, get_card, image_url
from .cases import roll_case_card
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


@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot) -> None:
    await message.answer(render.render_help(await _bot_username(bot)))


@router.message(Command("help"))
async def cmd_help(message: Message, bot: Bot) -> None:
    await message.answer(render.render_help(await _bot_username(bot)))


_SEEN_CHATS: set[int] = set()


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
async def cmd_admin(message: Message, db: Database, bot: Bot) -> None:
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


@router.message(Command("profile", "me", "профиль"))
@router.message(NormalizedText("профиль", "мой профиль"))
async def cmd_profile(message: Message, db: Database, market: MarketRepo) -> None:
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
    await message.answer(
        render.render_profile(profile, len(CARDS)),
        reply_markup=render.profile_keyboard(target_id),
    )


@router.callback_query(F.data.startswith("pf:"))
async def cb_profile(
    callback: CallbackQuery, db: Database, market: MarketRepo
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
        await _safe_edit(
            callback,
            render.render_profile(profile, len(CARDS)),
            render.profile_keyboard(target_id),
        )
        await callback.answer()
        return

    if action == "cards":
        text, units = await collection_data(db, market, target_id)
        await _safe_edit(callback, text, render.collection_keyboard(target_id, units))
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
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest as error:
        if "not modified" not in str(error).lower():
            log.warning("Не удалось обновить сообщение рынка: %s", error)


@router.message(Command("market", "рынок"))
async def cmd_market(message: Message, db: Database, market: MarketRepo) -> None:
    user = message.from_user
    if user is None:
        return
    await db.ensure_player(user.id, user.username, user.first_name)
    text, keyboard = await _market_view(market, user.id, 0)
    await message.answer(text, reply_markup=keyboard)


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
        card = get_card(lot["card_id"])
        lines.append(
            f"<code>#{lot['id']}</code> {card.rarity_emoji} {render.esc(card.display_name)} — "
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
# Рулетка и кейсы
# --------------------------------------------------------------------------- #


@router.message(Command("roulette", "рулетка"))
@router.message(NormalizedText("рулетка", "руль"))
async def cmd_roulette(message: Message, db: Database, market: MarketRepo) -> None:
    user = message.from_user
    if user is None:
        return
    await db.ensure_player(user.id, user.username, user.first_name)

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
        await db.add_card(user.id, str(value))

    balance = await market.balance(user.id)
    text = render.render_roulette(kind, value, balance)
    if spins_left:
        text += f"\n\n🎟 Осталось спинов сегодня: <b>{spins_left}</b>"
    await message.reply(text)


@router.message(Command("case", "кейс", "открыть"))
@router.message(NormalizedText("кейс", "открыть кейс"))
async def cmd_case(message: Message, db: Database) -> None:
    user = message.from_user
    if user is None:
        return
    await db.ensure_player(user.id, user.username, user.first_name)

    cases = await db.user_cases(user.id)
    if not cases:
        await message.answer(
            "📦 Кейсов нет. Крути рулетку: /roulette — или купи кейс на рынке: /market"
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


@router.message(Command("casino", "казино"))
@router.message(NormalizedText("казино"))
async def cmd_casino(message: Message, db: Database, market: MarketRepo) -> None:
    user = message.from_user
    if user is None:
        return
    await db.ensure_player(user.id, user.username, user.first_name)
    balance = await market.balance(user.id)
    parts = (message.text or "").split()[1:]
    if not parts:
        await message.answer(render.render_casino_help(balance))
        return

    raw = parts[0]
    if raw.lstrip("-").isdigit():
        amount = int(raw)
        if amount < casino.MIN_BET or amount > casino.MAX_BET:
            await message.answer(
                f"⚠️ Ставка от {casino.MIN_BET} до {casino.MAX_BET} очков."
            )
            return
        if balance < amount:
            await message.answer(f"⚠️ Не хватает очков: ставишь {amount}, у тебя {balance}.")
            return
        text, keyboard = render.render_casino_colors(f"💰 {amount} очков", f"p:{amount}")
    else:
        parsed = parse_handle(raw)
        if parsed is None:
            await message.answer("Не понял ставку. Смотри /casino")
            return
        try:
            unit = await market.owned_unit(user.id, parsed)
        except MarketError as error:
            await message.answer(f"⚠️ {error}")
            return
        card = get_card(unit["card_id"])
        token = "c:" + raw.lstrip("#")
        text, keyboard = render.render_casino_colors(
            f"{card.rarity_emoji} {render.esc(card.display_name)}", token
        )
    await message.answer(text, reply_markup=keyboard)


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
    repo = CasinoRepo(db, market)
    try:
        if token.startswith("p:"):
            result = await repo.bet_points(user_id, int(token[2:]), color)
        else:
            parsed = parse_handle(token[2:])
            if parsed is None:
                raise CasinoError("Не понял, какую карту ставим.")
            unit = await market.owned_unit(user_id, parsed)
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

    try:
        if step == "u":
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


def _app_url() -> str:
    base = (
        os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or ""
    ).rstrip("/")
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
    url = image_url(card.card_id)
    if url and callback.message is not None:
        try:
            await callback.bot.send_photo(
                chat_id=callback.message.chat.id,
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
    await _safe_edit(callback, text, keyboard)


@router.callback_query(F.data.startswith("my:"))
async def cb_my(callback: CallbackQuery, db: Database, market: MarketRepo) -> None:
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
        await _safe_edit(
            callback,
            render.render_profile(profile, len(CARDS)),
            render.profile_keyboard(user_id),
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
    else:
        await callback.answer()
        return
    await callback.answer()
