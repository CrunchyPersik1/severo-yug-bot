"""Сервис командного PvP: выбор карт, ходы, таймауты и публикация боя."""

from __future__ import annotations

import logging
import secrets
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery

from . import render, team_battle
from .cards import cards_sorted_for_user, get_card
from .config import settings
from .db import Database
from .market import effective_stats, parse_handle
from .market_repo import MarketRepo

log = logging.getLogger(__name__)


class TeamBattleError(Exception):
    """Ошибка, которую можно показать игроку."""


class TeamBattleService:
    def __init__(self, bot: Bot, db: Database, market: MarketRepo) -> None:
        self.bot = bot
        self.db = db
        self.market = market

    # ------------------------------------------------------------------ #
    # Создание
    # ------------------------------------------------------------------ #

    async def create(
        self,
        chat_id: int,
        author_id: int,
        people: list[dict[str, Any]],
        cards_per_player: int,
    ) -> str:
        """people: [{'user_id','name'}]. Первые двое — красные, следующие — синие."""
        if len(people) < 2:
            raise TeamBattleError("Нужно минимум двое участников.")
        if len(people) not in (2, 4):
            raise TeamBattleError("Командный бой — это 1 на 1 или 2 на 2.")
        if not 2 <= cards_per_player <= team_battle.MAX_CARDS:
            raise TeamBattleError(
                f"Карт на игрока: от 2 до {team_battle.MAX_CARDS}."
            )
        if author_id not in [p["user_id"] for p in people]:
            raise TeamBattleError("Ты должен быть среди участников боя.")

        for person in people:
            units = await self._units(person["user_id"])
            if not units:
                raise TeamBattleError(f"У {person['name']} нет карт.")

        battle_id = secrets.token_urlsafe(6)
        participants = []
        for index, person in enumerate(people):
            # 1 на 1 — по разные стороны; 2 на 2 — первые двое против вторых
            team = (
                team_battle.TEAM_RED
                if (index == 0 if len(people) == 2 else index < 2)
                else team_battle.TEAM_BLUE
            )
            participants.append(
                {
                    "user_id": person["user_id"],
                    "name": person["name"],
                    "team": team,
                    "picks": [],
                    "ready": False,
                }
            )
        state = {
            "mode": "team",
            "phase": "choosing",
            "cards_per_player": cards_per_player,
            "participants": participants,
            "author_id": author_id,
            "chat_id": chat_id,
            "log": [],
            "over": False,
            "winner": None,
        }
        await self.db.create_battle(battle_id, chat_id, author_id, None, state)
        for person in participants:
            await self._send_pick(battle_id, person["user_id"], chat_id)
        return battle_id

    async def _units(self, user_id: int) -> list[dict[str, Any]]:
        counts = await self.db.get_collection(user_id)
        units = [
            {
                "handle": f"#{card.card_id}",
                "card": card,
                "count": counts[card.card_id],
                "bonus": {},
                "stats": effective_stats(card, {}),
                "inventory_id": None,
            }
            for card in cards_sorted_for_user(list(counts))
        ]
        for row in await self.market.user_inventory(user_id):
            card = get_card(row["card_id"])
            units.append(
                {
                    "handle": f"#{row['id']}",
                    "card": card,
                    "count": 1,
                    "bonus": row["bonus"],
                    "stats": effective_stats(card, row["bonus"]),
                    "inventory_id": row["id"],
                }
            )
        return units

    async def _send_pick(self, battle_id: str, user_id: int, chat_id: int) -> None:
        battle = await self.db.get_battle(battle_id)
        if battle is None:
            return
        state = battle["state"]
        person = self._person(state, user_id)
        if person is None or person["ready"]:
            return
        units = await self._units(user_id)
        taken = set(person["picks"])
        units = [unit for unit in units if unit["handle"] not in taken]
        need = state["cards_per_player"]
        text, keyboard = render.render_team_pick(
            battle_id, units, len(person["picks"]), need
        )
        try:
            sent = await self.bot.send_message(user_id, text, reply_markup=keyboard)
        except (TelegramForbiddenError, TelegramBadRequest):
            text = f"<a href=\"tg://user?id={user_id}\">Игрок</a>, выбери карты.\n\n" + text
            sent = await self.bot.send_message(chat_id, text, reply_markup=keyboard)
        person["pick_chat"] = sent.chat.id
        person["pick_msg"] = sent.message_id

    @staticmethod
    def _person(state: dict[str, Any], user_id: int) -> dict[str, Any] | None:
        for person in state.get("participants", []):
            if person["user_id"] == user_id:
                return person
        return None

    # ------------------------------------------------------------------ #
    # Выбор карт
    # ------------------------------------------------------------------ #

    async def toggle_card(self, callback: CallbackQuery, battle_id: str, handle: str) -> None:
        user_id = callback.from_user.id
        started: dict[str, Any] = {}

        def mutator(battle: dict[str, Any], state: dict[str, Any]):
            if battle["status"] != "choosing":
                raise TeamBattleError("Бой уже начался.")
            person = self._person(state, user_id)
            if person is None:
                raise TeamBattleError("Ты не участник этого боя.")
            if person["ready"]:
                raise TeamBattleError("Ты уже выбрал карты.")
            if handle not in person["picks"]:
                person["picks"].append(handle)
            if len(person["picks"]) >= state["cards_per_player"]:
                person["ready"] = True
            if not all(p["ready"] for p in state["participants"]):
                return {"started": False}, None
            started["yes"] = True
            return {"started": True}, {"status": "active"}

        battle, _ = await self._commit(battle_id, mutator)
        if battle is None:
            raise TeamBattleError("Бой не найден.")
        if started.get("yes"):
            await self._build_and_publish(battle_id)
        else:
            await self._send_pick(battle_id, user_id, battle["chat_id"])

    async def _build_and_publish(self, battle_id: str) -> None:
        battle = await self.db.get_battle(battle_id)
        if battle is None:
            return
        state = battle["state"]
        picks: dict[int, list[dict[str, Any]]] = {}
        for person in state["participants"]:
            entries: list[dict[str, Any]] = []
            for handle in person["picks"]:
                parsed = parse_handle(handle)
                if parsed is None:
                    continue
                unit = await self.market.owned_unit(person["user_id"], parsed)
                bonus = await self.market.unit_bonus(unit["inventory_id"])
                card = get_card(unit["card_id"])
                entries.append(
                    {
                        "card": card,
                        "stats": effective_stats(card, bonus),
                        "handle": handle,
                    }
                )
            picks[person["user_id"]] = entries

        def mutator(row: dict[str, Any], current: dict[str, Any]):
            built = team_battle.build_state(
                current["participants"], picks, current["author_id"]
            )
            built["chat_id"] = current["chat_id"]
            built["author_id"] = current["author_id"]
            # имена участников нужны для отрисовки и итогов боя
            built["participants"] = current["participants"]
            current.clear()
            current.update(built)
            return None, None

        battle, _ = await self._commit(battle_id, mutator)
        if battle is not None:
            await self._publish(battle, force_new=True)

    async def _commit(self, battle_id: str, mutator):
        battle, result = await self.db.mutate_battle(battle_id, mutator)
        return battle, result

    # ------------------------------------------------------------------ #
    # Ходы
    # ------------------------------------------------------------------ #

    async def act(
        self,
        callback: CallbackQuery,
        battle_id: str,
        unit_key: str,
        action: str,
        target_key: str | None = None,
        ally_key: str | None = None,
    ) -> None:
        user_id = callback.from_user.id

        def mutator(battle: dict[str, Any], state: dict[str, Any]):
            if battle["status"] != "active" or state.get("over"):
                raise TeamBattleError("Бой уже закончен.")
            result = team_battle.perform(
                state, user_id, unit_key, action, target_key, ally_key
            )
            if not result["ok"]:
                raise TeamBattleError(result.get("error") or "Ход невозможен.")
            extra: dict[str, Any] = {}
            if state["over"]:
                extra["status"] = "finished"
                extra.update(self._finalize(state))
            return {"ok": True, "record": None}, extra or None

        battle, _ = await self._commit(battle_id, mutator)
        if battle is None:
            raise TeamBattleError("Бой не найден.")
        await self._publish(battle)

    def _finalize(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("recorded"):
            return {}
        state["recorded"] = True
        winner = state["winner"]
        winners = [
            p["user_id"] for p in state["participants"] if p["team"] == winner
        ] if winner else []
        losers = [
            p["user_id"] for p in state["participants"] if p["team"] != winner
        ] if winner else []
        return {"team_result": {"winners": winners, "losers": losers}}

    async def _publish(self, battle: dict[str, Any], force_new: bool = False) -> None:
        state = battle["state"]
        chat_id = battle["chat_id"]
        text, keyboard = render.render_team_battle(battle, state)
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
                log.warning("Командный бой %s не обновился: %s", battle["battle_id"], error)
            except TelegramForbiddenError:
                return
        try:
            sent = await self.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            log.warning("Командный бой %s не отправился: %s", battle["battle_id"], error)
            return
        await self.db.mutate_battle(
            battle["battle_id"],
            lambda b, s, c=chat_id, m=sent.message_id: (None, {"chat_id": c, "message_id": m}),
        )

    # ------------------------------------------------------------------ #
    # Таймауты
    # ------------------------------------------------------------------ #

    async def tick(self) -> None:
        stale = await self.db.stale_battles(settings.pick_timeout_seconds, team_battle.TIMEOUT_SECONDS)
        for battle in stale:
            state = battle["state"]
            if state.get("mode") != "team":
                continue
            battle_id = battle["battle_id"]
            try:
                if battle["status"] == "active":
                    await self._timeout_turn(battle_id)
                elif battle["status"] == "choosing":
                    await self._expire(battle_id)
            except Exception:  # noqa: BLE001
                log.exception("Ошибка таймаута командного боя %s", battle_id)

    async def _timeout_turn(self, battle_id: str) -> None:
        def mutator(battle: dict[str, Any], state: dict[str, Any]):
            if state.get("over"):
                return {"skipped": True}, None
            team_battle.register_timeout(state, state["turn"])
            extra: dict[str, Any] = {}
            if state["over"]:
                extra["status"] = "finished"
                extra.update(self._finalize(state))
            return {"skipped": False}, extra or None

        battle, _ = await self._commit(battle_id, mutator)
        if battle:
            await self._publish(battle)

    async def _expire(self, battle_id: str) -> None:
        def mutator(battle: dict[str, Any], state: dict[str, Any]):
            if battle["status"] != "choosing":
                return {"skipped": True}, None
            state["over"] = True
            state["log"].append("⌛ Карты не выбраны — бой отменён")
            return {"skipped": False}, {"status": "finished"}

        battle, _ = await self._commit(battle_id, mutator)
        if battle and battle.get("message_id"):
            await self._publish(battle)
