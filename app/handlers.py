"""Хэндлеры aiogram: выпадение карт, коллекция, лидерборд и PvP."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart, Filter
from aiogram.types import CallbackQuery, Message

from . import render
from .battle_service import BattleError, BattleService
from .cards import CARDS, cards_sorted_for_user
from .db import Database
from .gacha import day_key, next_reset, roll_card

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


@router.message(Command("my", "collection", "cards"))
async def cmd_collection(message: Message, db: Database) -> None:
    user = message.from_user
    if user is None:
        return
    await db.ensure_player(user.id, user.username, user.first_name)
    counts = await db.get_collection(user.id)
    cards = cards_sorted_for_user(list(counts))
    stats = await db.collection_stats(user.id)
    await message.answer(render.render_collection(cards, counts, stats, len(CARDS)))


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
