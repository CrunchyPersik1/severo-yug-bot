"""Сервис боёв: создание, выбор карт, ходы, таймауты, публикация в чат."""

from __future__ import annotations

import logging
import secrets
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from . import render
from .battle import (
    ACTION_ABILITY,
    ACTION_HIT,
    KEY_A,
    KEY_B,
    apply_action,
    new_state,
    other,
    side_for_user,
    surrender as engine_surrender,
)
from .cards import cards_sorted_for_user, get_card
from .config import settings
from .db import Database
from .market import effective_stats, parse_handle
from .market_repo import MarketError, MarketRepo
from .rewards import battle_reward

log = logging.getLogger(__name__)


class BattleError(Exception):
    """Ошибка, которую можно показать пользователю."""


def display_name(user: Any) -> str:
    if user is None:
        return "Игрок"
    if getattr(user, "first_name", None):
        return user.first_name
    if getattr(user, "username", None):
        return "@" + user.username
    return f"id{getattr(user, 'id', '?')}"


class BattleService:
    def __init__(self, bot: Bot, db: Database, market: MarketRepo | None = None) -> None:
        self.bot = bot
        self.db = db
        self.market = market or MarketRepo(db)

    async def units_for(self, user_id: int) -> list[dict[str, Any]]:
        """Всё, чем игрок может воевать: стаки из collection и улучшенные копии."""
        counts = await self.db.get_collection(user_id)
        units: list[dict[str, Any]] = []
        for card in cards_sorted_for_user(list(counts)):
            units.append(
                {
                    "handle": f"#{card.card_id}",
                    "card": card,
                    "count": counts[card.card_id],
                    "bonus": {},
                    "stats": effective_stats(card, {}),
                    "inventory_id": None,
                }
            )
        for instance in await self.market.user_inventory(user_id):
            card = get_card(instance["card_id"])
            units.append(
                {
                    "handle": f"#{instance['id']}",
                    "card": card,
                    "count": 1,
                    "bonus": instance["bonus"],
                    "stats": effective_stats(card, instance["bonus"]),
                    "inventory_id": instance["id"],
                }
            )
        return units

    # ------------------------------------------------------------------ #
    # Создание боя
    # ------------------------------------------------------------------ #

    async def create(self, message: Message, challenger: Any, opponent: Any) -> None:
        if opponent is None or getattr(opponent, "is_bot", False):
            raise BattleError("Нельзя вызвать бота. Ответь на сообщение игрока.")
        if challenger.id == opponent.id:
            raise BattleError("Нельзя вызвать самого себя.")
        if await self.db.user_active_battles(challenger.id) >= 1:
            raise BattleError("У тебя уже есть незавершённый бой.")
        if await self.db.user_active_battles(opponent.id) >= 1:
            raise BattleError("У соперника уже есть незавершённый бой.")

        if not await self.units_for(challenger.id):
            raise BattleError("У тебя нет карт. Напиши «Северо-Юг».")
        if not await self.units_for(opponent.id):
            raise BattleError(f"У {display_name(opponent)} нет карт.")

        battle_id = secrets.token_urlsafe(6)
        state: dict[str, Any] = {
            "phase": "choosing",
            "pick": {KEY_A: None, KEY_B: None},
            "sides": {
                KEY_A: {"user_id": challenger.id, "name": display_name(challenger)},
                KEY_B: {"user_id": opponent.id, "name": display_name(opponent)},
            },
            "turn": KEY_A,
            "turn_no": 0,
            "log": [],
            "over": False,
            "winner": None,
            "reason": None,
        }
        await self.db.ensure_player(opponent.id, getattr(opponent, "username", None), getattr(opponent, "first_name", None))
        await self.db.create_battle(
            battle_id, message.chat.id, challenger.id, opponent.id, state
        )

        await self._announce(message, battle_id, challenger, opponent)
        for key, user in ((KEY_A, challenger), (KEY_B, opponent)):
            await self._send_pick(battle_id, key, user, message.chat.id)

    async def _announce(self, message: Message, battle_id: str, challenger: Any, opponent: Any) -> None:
        text = (
            f"⚔️ <b>{render.esc(display_name(challenger))}</b> вызывает "
            f"<b>{render.esc(display_name(opponent))}</b> на бой!\n"
            f"Бой <code>{render.esc(battle_id)}</code>. Обоим отправлен выбор карты в личку."
        )
        try:
            await message.reply(text)
        except TelegramBadRequest:
            await self.bot.send_message(message.chat.id, text)

    async def _send_pick(self, battle_id: str, key: str, user: Any, fallback_chat_id: int) -> None:
        units = await self.units_for(user.id)
        opponent_name = "соперник"
        battle = await self.db.get_battle(battle_id)
        if battle:
            other_key = other(key)
            opponent_name = battle["state"]["sides"][other_key].get("name", "соперник")

        text, keyboard = render.render_pick(
            battle_id, units, 0, settings.cards_per_page, key, opponent_name, None
        )
        chat_id = user.id
        try:
            sent = await self.bot.send_message(chat_id, text, reply_markup=keyboard)
        except (TelegramForbiddenError, TelegramBadRequest):
            chat_id = fallback_chat_id
            text = f"<a href=\"tg://user?id={user.id}\">Игрок</a>, выбери карту.\n\n" + text
            sent = await self.bot.send_message(chat_id, text, reply_markup=keyboard)
        await self.db.mutate_battle(
            battle_id,
            lambda b, s, k=key, c=chat_id, m=sent.message_id: (
                None,
                {f"pick_{k}_chat": c, f"pick_{k}_msg": m},
            ),
        )

    # ------------------------------------------------------------------ #
    # Транзакционные операции
    # ------------------------------------------------------------------ #

    async def _commit(self, battle_id: str, mutator) -> tuple[dict[str, Any] | None, Any]:
        battle, result = await self.db.mutate_battle(battle_id, mutator)
        if battle is None:
            return None, None
        record = result.get("record") if isinstance(result, dict) else None
        if record:
            await self.db.apply_battle_result(**record)
        elif battle["status"] == "finished" and not battle["state"].get("recorded"):
            log.warning("Бой %s завершён без записи результата", battle_id)
        return battle, result

    async def choose_card(self, callback: CallbackQuery, battle_id: str, handle: str) -> None:
        user_id = callback.from_user.id
        parsed = parse_handle(handle)
        if parsed is None:
            raise BattleError("Непонятная карта.")
        try:
            unit = await self.market.owned_unit(user_id, parsed)
        except MarketError as error:
            raise BattleError(str(error)) from error
        bonus = await self.market.unit_bonus(unit["inventory_id"])

        started: dict[str, Any] = {}

        def mutator(battle: dict[str, Any], state: dict[str, Any]):
            if battle["status"] != "choosing":
                raise BattleError("Бой уже начался.")
            key = side_for_user(state, user_id)
            if key is None:
                raise BattleError("Ты не участник этого боя.")
            state["pick"][key] = {
                "handle": handle,
                "card_id": unit["card_id"],
                "inventory_id": unit["inventory_id"],
                "bonus": bonus,
            }
            if not all(state["pick"].values()):
                return {"started": False}, None

            picks = {k: state["pick"][k] for k in (KEY_A, KEY_B)}
            card_a = get_card(picks[KEY_A]["card_id"])
            card_b = get_card(picks[KEY_B]["card_id"])
            names = {k: state["sides"][k].get("name") for k in (KEY_A, KEY_B)}
            ids = {k: state["sides"][k]["user_id"] for k in (KEY_A, KEY_B)}
            new = new_state(
                card_a,
                card_b,
                first=KEY_A,
                stats_a=effective_stats(card_a, picks[KEY_A]["bonus"]),
                stats_b=effective_stats(card_b, picks[KEY_B]["bonus"]),
            )
            new["phase"] = "battle"
            for k in (KEY_A, KEY_B):
                new["sides"][k]["user_id"] = ids[k]
                new["sides"][k]["name"] = names[k]
            new["log"].append(f"🃏 {card_a.name} против {card_b.name}")
            state.clear()
            state.update(new)
            started["yes"] = True
            return {"started": True}, {"status": "active", "turn_no": 1}

        battle, _ = await self._commit(battle_id, mutator)
        if battle is None:
            raise BattleError("Бой не найден.")
        if started.get("yes"):
            await self._publish(battle, force_new=True)

    async def act(self, callback: CallbackQuery, battle_id: str, action: str) -> None:
        user_id = callback.from_user.id
        outcome: dict[str, Any] = {}

        def mutator(battle: dict[str, Any], state: dict[str, Any]):
            if battle["status"] != "active":
                raise BattleError("Этот бой уже не идёт.")
            key = side_for_user(state, user_id)
            if key is None:
                raise BattleError("Ты не участник этого боя.")
            result = apply_action(
                state,
                key,
                ACTION_ABILITY if action == ACTION_ABILITY else ACTION_HIT,
                max_turns=settings.battle_max_turns,
                max_timeouts=settings.battle_max_timeouts,
            )
            if not result["ok"]:
                raise BattleError(result["error"] or "Ход невозможен.")
            extra: dict[str, Any] | None = None
            record: dict[str, Any] | None = None
            if state["over"]:
                extra = {"status": "finished"}
                record = self._finalize(state)
            outcome.update(result)
            # record обязан ехать в result: _commit читает его именно оттуда.
            return {"ok": True, "record": record}, extra

        battle, _ = await self._commit(battle_id, mutator)
        if battle is None:
            raise BattleError("Бой не найден.")
        await self._publish(battle)

    async def surrender(self, callback: CallbackQuery, battle_id: str) -> None:
        user_id = callback.from_user.id

        def mutator(battle: dict[str, Any], state: dict[str, Any]):
            if battle["status"] == "finished":
                raise BattleError("Бой уже закончен.")
            key = side_for_user(state, user_id)
            if key is None:
                raise BattleError("Ты не участник этого боя.")
            if battle["status"] == "choosing":
                state["over"] = True
                state["winner"] = other(key)
                state["reason"] = "cancel"
                state["log"].append("❌ Бой отменён")
                return {"cancelled": True, "record": None}, {"status": "finished"}
            engine_surrender(state, key)
            return {"cancelled": False, "record": self._finalize(state)}, {"status": "finished"}

        battle, _ = await self._commit(battle_id, mutator)
        if battle is None:
            raise BattleError("Бой не найден.")
        if battle["status"] == "finished" and not battle["state"]["sides"][KEY_A].get("card_id"):
            return
        await self._publish(battle)

    def _finalize(self, state: dict[str, Any]) -> dict[str, Any] | None:
        """Идемпотентно фиксирует результат боя (один раз).

        Возвращает запись для apply_battle_result или None, если уже записано.
        """
        if state.get("recorded"):
            return None
        state["recorded"] = True
        winner = state["winner"]
        sides = state["sides"]
        ids = {k: sides[k]["user_id"] for k in (KEY_A, KEY_B)}
        cards = {k: sides[k]["card_id"] for k in (KEY_A, KEY_B)}
        if winner == "draw":
            return {
                "winner_id": ids[KEY_A],
                "loser_id": ids[KEY_B],
                "draw": True,
            }
        loser_key = other(winner)
        reward = battle_reward(get_card(cards[loser_key]).points)
        state["reward"] = {
            "amount": reward,
            "winner": winner,
            "loser_card": cards[loser_key],
        }
        return {
            "winner_id": ids[winner],
            "loser_id": ids[loser_key],
            "draw": False,
            "winner_card_id": cards[winner],
            "loser_card_id": cards[loser_key],
            "stake": reward,
        }

    # ------------------------------------------------------------------ #
    # Публикация
    # ------------------------------------------------------------------ #

    async def set_message(self, battle_id: str, chat_id: int, message_id: int) -> None:
        await self.db.mutate_battle(
            battle_id, lambda b, s: (None, {"chat_id": chat_id, "message_id": message_id})
        )

    async def _publish(self, battle: dict[str, Any], force_new: bool = False) -> None:
        state = battle["state"]
        chat_id = battle["chat_id"]
        text, keyboard = render.render_battle(battle, state)
        message_id = None if force_new else battle.get("message_id")

        if message_id:
            try:
                await self.bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id, text=text, reply_markup=keyboard
                )
                return
            except TelegramBadRequest as error:
                if "not modified" in str(error).lower():
                    return
                log.warning("Не удалось отредактировать бой %s: %s", battle["battle_id"], error)
            except TelegramForbiddenError:
                return

        try:
            sent = await self.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            log.warning("Не удалось отправить бой %s: %s", battle["battle_id"], error)
            return
        await self.set_message(battle["battle_id"], chat_id, sent.message_id)

    # ------------------------------------------------------------------ #
    # Таймауты
    # ------------------------------------------------------------------ #

    async def tick(self) -> None:
        stale = await self.db.stale_battles(settings.pick_timeout_seconds, settings.battle_timeout_seconds)
        for battle in stale:
            battle_id = battle["battle_id"]
            try:
                if battle["status"] == "choosing":
                    await self._expire_choice(battle_id)
                elif battle["status"] == "active":
                    await self._auto_turn(battle_id)
            except Exception:  # noqa: BLE001 - цикл не должен падать
                log.exception("Ошибка обработки таймаута боя %s", battle_id)

    async def _expire_choice(self, battle_id: str) -> None:
        def mutator(battle: dict[str, Any], state: dict[str, Any]):
            if battle["status"] != "choosing":
                return {"skipped": True}, None
            state["over"] = True
            state["winner"] = None
            state["reason"] = "pick_timeout"
            state["log"].append("⌛ Карты не выбраны — бой отменён")
            return {"skipped": False}, {"status": "finished"}

        battle, result = await self._commit(battle_id, mutator)
        if battle and result and not result.get("skipped"):
            if battle.get("message_id"):
                await self._publish(battle)

    async def _auto_turn(self, battle_id: str) -> None:
        def mutator(battle: dict[str, Any], state: dict[str, Any]):
            if battle["status"] != "active" or state["over"]:
                return {"skipped": True, "record": None}, None
            key = state["turn"]
            result = apply_action(
                state,
                key,
                ACTION_HIT,
                max_turns=settings.battle_max_turns,
                max_timeouts=settings.battle_max_timeouts,
                register_timeout=True,
            )
            extra: dict[str, Any] | None = None
            record: dict[str, Any] | None = None
            if state["over"]:
                extra = {"status": "finished"}
                record = self._finalize(state)
            return {**result, "record": record}, extra

        battle, _ = await self._commit(battle_id, mutator)
        if battle:
            await self._publish(battle)

    # ------------------------------------------------------------------ #
    # Пулы выбора карт (страницы)
    # ------------------------------------------------------------------ #

    async def repaginate(self, callback: CallbackQuery, battle_id: str, page: int) -> None:
        battle = await self.db.get_battle(battle_id)
        if battle is None or battle["status"] != "choosing":
            raise BattleError("Бой больше не доступен.")
        state = battle["state"]
        key = side_for_user(state, callback.from_user.id)
        if key is None:
            raise BattleError("Ты не участник этого боя.")
        units = await self.units_for(callback.from_user.id)
        other_key = other(key)
        opponent_name = state["sides"][other_key].get("name", "соперник")
        picked = state["pick"].get(key)
        picked_label = picked["handle"] if isinstance(picked, dict) else None
        text, keyboard = render.render_pick(
            battle_id,
            units,
            page,
            settings.cards_per_page,
            key,
            opponent_name,
            picked_label,
        )
        try:
            await callback.message.edit_text(text, reply_markup=keyboard)
        except TelegramBadRequest as error:
            if "not modified" not in str(error).lower():
                raise BattleError("Не удалось обновить список.") from error
