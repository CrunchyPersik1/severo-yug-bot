"""Интеграционные тесты слоя БД. Требуют TEST_DATABASE_URL (Postgres).

Локально пропускаются, в CI поднимается сервис-контейнер postgres.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta, timezone

import pytest

from app.battle import KEY_A, KEY_B, new_state
from app.cards import CARDS, card_rows, get_card
from app.db import Database
from app.gacha import day_key

DSN = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL не задан")


def run(coro):
    return asyncio.run(coro)


async def fresh_db() -> Database:
    db = Database(DSN or "")
    await db.connect()
    await db.init_schema()
    await db.upsert_cards(card_rows())
    return db


def test_schema_and_cards_upsert():
    async def scenario():
        db = await fresh_db()
        try:
            async with db.pool.acquire() as con:
                count = await con.fetchval("select count(*) from cards")
                assert count == len(CARDS) == 32
            # повторный upsert не должен падать и не должен дублировать
            await db.upsert_cards(card_rows())
            async with db.pool.acquire() as con:
                assert await con.fetchval("select count(*) from cards") == 32
        finally:
            await db.close()

    run(scenario())


def test_daily_limit_is_atomic():
    async def scenario():
        db = await fresh_db()
        try:
            user = 900001
            async with db.pool.acquire() as con:
                await con.execute("delete from collection where user_id = $1", user)
                await con.execute("delete from players where user_id = $1", user)
            await db.ensure_player(user, "tester", "Тестер")
            today = day_key()
            assert await db.claim_daily(user, today) is True
            assert await db.claim_daily(user, today) is False
            tomorrow = today + timedelta(days=1)
            assert await db.claim_daily(user, tomorrow) is True
        finally:
            await db.close()

    run(scenario())


def test_collection_counts_and_points():
    async def scenario():
        db = await fresh_db()
        try:
            user = 900002
            async with db.pool.acquire() as con:
                await con.execute("delete from collection where user_id = $1", user)
                await con.execute("delete from players where user_id = $1", user)
            await db.ensure_player(user, None, "Второй")
            assert await db.add_card(user, "oleg") == 1
            assert await db.add_card(user, "oleg") == 2
            assert await db.add_card(user, "valeriya") == 1
            collection = await db.get_collection(user)
            assert collection == {"oleg": 2, "valeriya": 1}
            stats = await db.collection_stats(user)
            assert stats["unique_cards"] == 2
            assert stats["total_cards"] == 3
            assert stats["points"] == 250 + 15000
            await db.add_drop(user, -100, "oleg", day_key())
            top = await db.top_players(10)
            assert any(row["user_id"] == user for row in top)
        finally:
            await db.close()

    run(scenario())


def test_battle_lifecycle_and_locking():
    async def scenario():
        db = await fresh_db()
        try:
            battle_id = "test-battle-1"
            async with db.pool.acquire() as con:
                await con.execute("delete from battles where battle_id = $1", battle_id)
            state = new_state(get_card("oleg"), get_card("karina"))
            state["sides"][KEY_A]["user_id"] = 1
            state["sides"][KEY_B]["user_id"] = 2
            await db.create_battle(battle_id, -100, 1, 2, state)

            def mutator(battle, state):
                state["turn_no"] = 7
                return {"ok": True}, {"status": "active"}

            battle, result = await db.mutate_battle(battle_id, mutator)
            assert result == {"ok": True}
            assert battle["status"] == "active"
            assert battle["version"] == 1

            reloaded = await db.get_battle(battle_id)
            assert reloaded is not None
            assert reloaded["state"]["turn_no"] == 7
            assert isinstance(reloaded["state"], dict)

            # FOR UPDATE не даёт потерять обновление: два мутатора подряд
            await db.mutate_battle(battle_id, lambda b, s: (None, {"status": "finished"}))
            final = await db.get_battle(battle_id)
            assert final["status"] == "finished"
            assert final["version"] == 2

            missing, result = await db.mutate_battle("no-such-battle", lambda b, s: (1, None))
            assert missing is None and result is None
        finally:
            await db.close()

    run(scenario())


def test_stale_battles_detection():
    async def scenario():
        db = await fresh_db()
        try:
            battle_id = "test-stale-1"
            async with db.pool.acquire() as con:
                await con.execute("delete from battles where battle_id = $1", battle_id)
            state = new_state(get_card("oleg"), get_card("oleg"))
            await db.create_battle(battle_id, -100, 11, 22, state)
            fresh = await db.get_battle(battle_id)
            assert fresh is not None
            stale = await db.stale_battles(choosing_seconds=600, active_seconds=60)
            assert all(b["battle_id"] != battle_id for b in stale)
            # состарим запись
            async with db.pool.acquire() as con:
                await con.execute(
                    "update battles set updated_at = now() - interval '2 hours' where battle_id = $1",
                    battle_id,
                )
            stale = await db.stale_battles(choosing_seconds=600, active_seconds=60)
            assert any(b["battle_id"] == battle_id for b in stale)
            await db.mutate_battle(battle_id, lambda b, s: (None, {"status": "finished"}))
        finally:
            await db.close()

    run(scenario())

def test_battle_result_transfers_points_and_kills():
    async def scenario():
        db = await fresh_db()
        try:
            winner, loser = 900003, 900004
            async with db.pool.acquire() as con:
                await con.execute(
                    "delete from collection where user_id = any($1::bigint[])", [winner, loser]
                )
                await con.execute("delete from players where user_id = any($1::bigint[])", [winner, loser])
            await db.ensure_player(winner, None, "Победитель")
            await db.ensure_player(loser, None, "Проигравший")
            await db.add_card(winner, "oleg")
            await db.add_card(loser, "daniel")

            stake = 500  # 5% от 10000
            await db.apply_battle_result(
                winner_id=winner,
                loser_id=loser,
                draw=False,
                winner_card_id="oleg",
                loser_card_id="daniel",
                stake=stake,
            )

            winner_profile = await db.player_profile(winner)
            loser_profile = await db.player_profile(loser)
            assert winner_profile["wins"] == 1
            assert winner_profile["kills"] == 1
            assert winner_profile["bonus_points"] == stake
            assert winner_profile["card_points"] == 250
            assert winner_profile["total"] == stake  # очки — единая валюта
            assert winner_profile["rank"] == 1

            assert loser_profile["losses"] == 1
            assert loser_profile["bonus_points"] == -stake
            assert loser_profile["total"] == 0  # минус на балансе показываем нулём
            assert loser_profile["wins"] == 0

            kills = await db.get_card_kills(winner)
            assert kills["oleg"] == 1

            rating = await db.rating(10)
            assert rating[0]["user_id"] == winner
            assert rating[0]["kills"] == 1
        finally:
            await db.close()

    run(scenario())


def test_draw_gives_nothing():
    async def scenario():
        db = await fresh_db()
        try:
            first, second = 900005, 900006
            async with db.pool.acquire() as con:
                await con.execute("delete from players where user_id = any($1::bigint[])", [first, second])
            await db.ensure_player(first, None, "A")
            await db.ensure_player(second, None, "B")
            await db.apply_battle_result(winner_id=first, loser_id=second, draw=True)
            profile = await db.player_profile(first)
            assert profile["draws"] == 1
            assert profile["wins"] == 0
            assert profile["bonus_points"] == 0
            assert profile["kills"] == 0
        finally:
            await db.close()

    run(scenario())
