"""Регрессия: результат боя обязан попадать в БД.

Баг был в том, что мутатор клал record в extra, а _commit читал его из result,
поэтому apply_battle_result не вызывался никогда: не начислялись победы,
убийства и очки. Тест повторяет семантику настоящего Database.mutate_battle.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import Chat, Message

from app.battle import KEY_A, KEY_B, new_state
from app.battle_service import BattleError, BattleService
from app.cards import get_card
from app.rewards import battle_reward


class EditSession(BaseSession):
    async def close(self) -> None:  # pragma: no cover
        return None

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None) -> Any:
        if type(method).__name__ in {"SendMessage", "EditMessageText"}:
            return Message(
                message_id=10,
                date=datetime.now(timezone.utc),
                chat=Chat(id=getattr(method, "chat_id", 1), type="private"),
            )
        return True

    async def stream_content(self, *args: Any, **kwargs: Any):  # pragma: no cover
        yield b""


class FakeBattleDB:
    """Повторяет контракт Database.mutate_battle: возвращает (battle, result)."""

    def __init__(self, battle: dict[str, Any]) -> None:
        self.battle = battle
        self.results: list[dict[str, Any]] = []

    async def mutate_battle(self, battle_id: str, mutator):
        result, extra = mutator(self.battle, self.battle["state"])
        if extra:
            self.battle.update(extra)
        return self.battle, result

    async def apply_battle_result(self, **kwargs: Any) -> None:
        self.results.append(kwargs)

    async def get_battle(self, battle_id: str):
        return self.battle


class FakeCallback:
    def __init__(self, user_id: int) -> None:
        self.from_user = type("U", (), {"id": user_id})()
        self.answers: list[str] = []

    async def answer(self, text: str | None = None, **kwargs: Any) -> None:
        self.answers.append(text or "")


def build_battle(card_a: str = "oleg", card_b: str = "karina", b_hp: int = 1) -> dict[str, Any]:
    state = new_state(get_card(card_a), get_card(card_b))
    state["sides"][KEY_A]["user_id"] = 111
    state["sides"][KEY_B]["user_id"] = 222
    state["sides"][KEY_A]["name"] = "Первый"
    state["sides"][KEY_B]["name"] = "Второй"
    state["sides"][KEY_B]["hp"] = b_hp
    return {
        "battle_id": "b1",
        "chat_id": -100,
        "message_id": 10,
        "challenger_id": 111,
        "opponent_id": 222,
        "status": "active",
        "state": state,
        "turn_no": 1,
        "winner_id": None,
        "version": 0,
    }


def run_battle(battle: dict[str, Any], user_id: int, action: str = "hit"):
    db = FakeBattleDB(battle)
    bot = Bot(token="123456:TEST", session=EditSession())
    service = BattleService(bot, db)
    callback = FakeCallback(user_id)
    asyncio.run(service.act(callback, "b1", action))
    return db


def test_winning_strike_records_result():
    battle = build_battle()
    db = run_battle(battle, 111)
    assert len(db.results) == 1, "результат боя обязан уйти в apply_battle_result"
    record = db.results[0]
    assert record["winner_id"] == 111
    assert record["loser_id"] == 222
    assert record["draw"] is False
    assert record["winner_card_id"] == "oleg"
    assert record["loser_card_id"] == "karina"
    assert record["stake"] == battle_reward(get_card("karina").points) == 25


def test_result_is_recorded_only_once():
    battle = build_battle()
    db = run_battle(battle, 111)
    assert len(db.results) == 1
    try:
        asyncio.run(BattleService(Bot(token="1:T", session=EditSession()), db).act(FakeCallback(111), "b1", "hit"))
    except BattleError:
        pass
    assert len(db.results) == 1, "повторный ход не должен начислять награду дважды"


def test_surrender_records_result():
    battle = build_battle(b_hp=90)
    db = FakeBattleDB(battle)
    bot = Bot(token="123456:TEST", session=EditSession())
    service = BattleService(bot, db)
    asyncio.run(service.surrender(FakeCallback(222), "b1"))
    assert len(db.results) == 1
    assert db.results[0]["winner_id"] == 111
    assert db.results[0]["loser_id"] == 222


def test_timeout_records_result():
    battle = build_battle(b_hp=90)
    battle["state"]["sides"][KEY_A]["timeouts"] = 2
    db = FakeBattleDB(battle)
    bot = Bot(token="123456:TEST", session=EditSession())
    service = BattleService(bot, db)
    battle["state"]["turn"] = KEY_A
    asyncio.run(service._auto_turn("b1"))
    assert len(db.results) == 1
    assert db.results[0]["winner_id"] == 222
    assert db.results[0]["stake"] == battle_reward(get_card("oleg").points)
