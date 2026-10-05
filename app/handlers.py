"""Хэндлеры aiogram: выпадение карт, коллекция, лидерборд и PvP."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart, Filter
from aiogram.types import CallbackQuery, Message

from . import render
from .battle_service import BattleError, BattleService
from .cards import CARDS, cards_sorted_for_user, get_card
from .db import Database
from .gacha import day_key, next_reset, roll_card
from .items import SLOT_ICONS
from .market import (
    RATING_MIN_TO_SELL,
    can_sell,
    describe_bonus,
    effective_stats,
    market_price,
    parse_handle,
    price_ratio,
    seller_income,
)
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


@router.message(Command("drop", "daily", "карта"))
@router.message(NormalizedText("северо-юг", "север юг", "северо юг"))
async def cmd_drop(message: Message, db: Database) -> None:
    user = message.from_user
    if user is None:
        return
    await db.ensure_player(user.id, user.username, user.first_name)

    today = day_key()
    if not await db.claim_daily(user.id, today):
        left = (next_reset() - datetime.now(timezone.utc)).total_seconds()
        await message.reply(
            f"⏳ Сегодня карта уже выпадала. Следующая — через {_humanize(left)} "
            "(сброс в 12:00 по ЕКБ)."
        )
        return

    card = roll_card()
    counts = await db.get_collection(user.id)
    is_new = card.card_id not in counts
    count = await db.add_card(user.id, card.card_id)
    await db.add_drop(user.id, message.chat.id, card.card_id, today)

    await message.reply(render.render_drop(card, count, is_new))


def upgrade_items(row: dict[str, Any]) -> list[str]:
    """Читаемые названия прикреплённых улучшений."""
    out: list[str] = []
    for slot in ("aura", "background", "effect"):
        item = item_of(slot, row.get(f"{slot}_id"))
        if item:
            out.append(f"{SLOT_ICONS[slot]} {item.name} ({item.summary})")
    return out


def decorate_lot(lot: dict[str, Any]) -> dict[str, Any]:
    """Досчитывает статы и разворачивает улучшения для отображения лота."""
    card = get_card(lot["card_id"])
    bonus = lot.get("bonus") or {}
    lot["stats"] = effective_stats(card, bonus)
    lot["bonus"] = bonus
    for slot in ("aura", "background", "effect"):
        item = item_of(slot, lot.get(f"{slot}_id"))
        lot[slot] = (
            {"name": item.name, "icon": SLOT_ICONS[slot], "summary": item.summary}
            if item
            else None
        )
    return lot


@router.message(Command("my", "collection", "cards"))
async def cmd_collection(message: Message, db: Database, market: MarketRepo) -> None:
    user = message.from_user
    if user is None:
        return
    await db.ensure_player(user.id, user.username, user.first_name)
    counts = await db.get_collection(user.id)
    kills = await db.get_card_kills(user.id)
    cards = cards_sorted_for_user(list(counts))
    stats = await db.collection_stats(user.id)
    instances = []
    for row in await market.user_inventory(user.id):
        card = get_card(row["card_id"])
        instances.append(
            {
                "inventory_id": row["id"],
                "card": card,
                "stats": effective_stats(card, row["bonus"]),
                "items": upgrade_items(row),
            }
        )
    await message.answer(
        render.render_collection(cards, counts, kills, stats, len(CARDS), instances)
    )


@router.message(Command("profile", "me", "профиль"))
async def cmd_profile(message: Message, db: Database) -> None:
    user = message.from_user
    if user is None:
        return
    await db.ensure_player(user.id, user.username, user.first_name)
    profile = await db.player_profile(user.id)
    if profile is None:
        await message.answer("Профиль пока пуст. Напиши «Северо-Юг».")
        return
    await message.answer(render.render_profile(profile, len(CARDS)))


@router.message(Command("pvprating", "пвптоп", "pvp_top"))
async def cmd_pvp_rating(message: Message, db: Database) -> None:
    rows = await db.rating(10)
    await message.answer(render.render_rating(rows))


@router.message(Command("top", "leaderboard"))
async def cmd_top(message: Message, db: Database) -> None:
    rows = await db.top_players(10)
    lines = ["🏆 <b>Лидерборд коллекций</b>", ""]
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
    await callback.answer(f"Куплено: {card.name}", show_alert=True)
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

    card = get_card(lot["card_id"])
    lines = [
        f"✅ Лот <code>#{lot['id']}</code> выставлен",
        f"{card.rarity_emoji} <b>{render.esc(card.name)}</b> за <b>{price}</b> очк.",
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
            f"<code>#{lot['id']}</code> {card.rarity_emoji} {render.esc(card.name)} — "
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
    card = get_card(unit["card_id"])
    await message.answer(
        f"🎁 <b>{render.esc(card.name)}</b> подарена игроку {render.esc(target_name)}"
    )


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
            "Улучшенную копию можно улучшать дальше, пока не займутся все три слота."
        )
        return
    parsed = parse_handle(parts[0])
    if parsed is None:
        await message.answer("Не понял карту. Загляни в /my")
        return
    try:
        if parsed[0] == "card":
            outcome = await market.upgrade_stack(user.id, str(parsed[1]))
        else:
            outcome = await market.upgrade_instance(user.id, int(parsed[1]))
    except MarketError as error:
        await message.answer(f"⚠️ {error}")
        return

    card = get_card(outcome["card_id"])
    item = outcome["item"]
    left = 3 - int(outcome.get("filled", 1))
    lines = [
        f"⚡ <b>{render.esc(card.name)}</b> улучшена — копия <code>#{outcome['inventory_id']}</code>",
        f"{SLOT_ICONS[outcome['slot']]} <b>{render.esc(item.name)}</b> — {render.esc(item.summary)}",
    ]
    if left > 0:
        lines.append(f"Свободных слотов: {left}. Дальше: <code>/upgrade #{outcome['inventory_id']}</code>")
    else:
        lines.append("Все три слота заняты — перебить или заменить нельзя.")
    await message.answer("\n".join(lines))


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
                        f"Игрок {render.esc(part)} не найден. "
                        "Пусть он сначала напишет боту, либо ответь на его сообщение."
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
    await message.answer(
        render.render_rating_profile(profile, stats["deals"], stats["gifts"])
    )
