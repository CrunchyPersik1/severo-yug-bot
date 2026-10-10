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
                assert count == len(CARDS)
            # повторный upsert не должен падать и не должен дублировать
            await db.upsert_cards(card_rows())
            async with db.pool.acquire() as con:
                assert await con.fetchval("select count(*) from cards") == len(CARDS)
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
            assert await db.claim_daily(user, today) is not None
            assert await db.claim_daily(user, today) is None
            tomorrow = today + timedelta(days=1)
            assert await db.claim_daily(user, tomorrow) is not None
        finally:
            await db.close()

    run(scenario())


def test_grant_drop_limit_adds_attempts_for_today():
    async def scenario():
        db = await fresh_db()
        try:
            user = 900007
            async with db.pool.acquire() as con:
                await con.execute("delete from players where user_id = $1", user)
            await db.ensure_player(user, None, "Лимитчик")
            today = day_key()
            # базовый лимит 1 + 5 = 6 попыток
            assert await db.grant_drop_limit(user, today, 5) == 6
            assert await db.claim_daily(user, today) == 5
            assert await db.claim_daily(user, today) == 4
            # на следующий день лимит снова обычный
            tomorrow = today + timedelta(days=1)
            assert await db.claim_daily(user, tomorrow) == 0
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


def test_stocks_buy_sell_and_no_arbitrage():
    async def scenario():
        db = await fresh_db()
        try:
            from app import stocks as stocks_mod
            from app.stocks_repo import StocksError, StocksRepo

            repo = StocksRepo(db)
            await repo.seed()
            user = 900010
            async with db.pool.acquire() as con:
                await con.execute("delete from stock_holdings where user_id = $1", user)
                await con.execute("delete from players where user_id = $1", user)
            await db.ensure_player(user, None, "Трейдер")
            await db.add_points(user, 1_000_000)

            await repo.tick()
            before = (await repo.overview(user))["me"]["balance"]

            bought = await repo.buy(user, "syug", 10)
            assert bought["shares"] == 10
            # больше, чем есть, продать нельзя
            with pytest.raises(StocksError):
                await repo.sell(user, "syug", 99)

            sold = await repo.sell(user, "syug", 10)
            assert sold["shares"] == 10

            after = (await repo.overview(user))["me"]["balance"]
            # покупка и продажа по одному курсу съедают комиссию
            assert after < before, "круговой трейд не должен приносить очки"

            overview = await repo.overview(user)
            assert len(overview["stocks"]) == len(stocks_mod.STOCKS)
            assert overview["portfolio"]["value"] == 0
        finally:
            async with db.pool.acquire() as con:
                await con.execute("delete from stock_holdings where user_id = 900010")
                await con.execute("delete from players where user_id = 900010")
            await db.close()

    run(scenario())


def test_stocks_tick_survives_broken_pump_table():
    """Если расписание пампов сломалось, курс всё равно должен двигаться."""

    async def scenario():
        db = await fresh_db()
        try:
            from app.stocks_repo import StocksRepo

            repo = StocksRepo(db)
            await repo.seed()
            async with db.pool.acquire() as con:
                await con.execute("drop table if exists stock_pumps")
                await con.execute(
                    "update stocks set volatility = 0, target_price = price * 2, "
                    "updated_at = now() - interval '30 seconds' where slug = 'syug'"
                )
                before = int(
                    await con.fetchval("select price from stocks where slug = 'syug'")
                )
            await repo.tick()
            async with db.pool.acquire() as con:
                after = int(
                    await con.fetchval("select price from stocks where slug = 'syug'")
                )
            assert after > before, "без таблицы пампов курс всё равно должен идти"
        finally:
            async with db.pool.acquire() as con:
                await con.execute(
                    "create table if not exists stock_pumps ("
                    "id integer primary key, "
                    "next_at timestamptz not null default now())"
                )
            await db.close()

    run(scenario())


def test_stocks_pump_rises_and_returns():
    async def scenario():
        db = await fresh_db()
        try:
            from app.stocks_repo import StocksRepo

            repo = StocksRepo(db)
            await repo.seed()
            async with db.pool.acquire() as con:
                row = await con.fetchrow(
                    "select id, price from stocks where slug = 'syug'"
                )
                sid = int(row["id"])
                start = int(row["price"])
                await con.execute(
                    """
                    update stocks
                       set pump_phase = 'up', pump_peak = $2, pump_home = $3,
                           target_price = null,
                           updated_at = now() - interval '20 seconds'
                     where id = $1
                    """,
                    sid,
                    start * 3,
                    start,
                )
            await repo.tick()
            async with db.pool.acquire() as con:
                mid = int(await con.fetchval("select price from stocks where id = $1", sid))
            assert mid > start, "курс должен взлетать"

            state = None
            for _ in range(60):
                async with db.pool.acquire() as con:
                    await con.execute(
                        "update stocks set updated_at = now() - interval '20 seconds' "
                        "where id = $1",
                        sid,
                    )
                await repo.tick()
                async with db.pool.acquire() as con:
                    state = await con.fetchrow(
                        "select price, pump_phase from stocks where id = $1", sid
                    )
                if state["pump_phase"] is None:
                    break
            assert state is not None and state["pump_phase"] is None, "памп закончился"
            assert int(state["price"]) == start, "курс вернулся к прежней цене"
        finally:
            await db.close()

    run(scenario())


def test_stocks_cap_on_buy_and_refund_of_excess():
    async def scenario():
        db = await fresh_db()
        try:
            from app.stocks_repo import StocksError, StocksRepo

            repo = StocksRepo(db)
            await repo.seed()
            user = 900012
            async with db.pool.acquire() as con:
                await con.execute("delete from stock_holdings where user_id = $1", user)
                await con.execute("delete from players where user_id = $1", user)
            await db.ensure_player(user, None, "Кит")
            await db.add_points(user, 10_000_000)

            await repo.buy(user, "syug", 100)
            with pytest.raises(StocksError):
                await repo.buy(user, "syug", 1)

            # Искусственно раздуваем холдинг: seed должен срезать излишек.
            async with db.pool.acquire() as con:
                await con.execute(
                    "update stock_holdings set shares = 150, spent = 150000 "
                    "where user_id = $1",
                    user,
                )
                before = int(
                    await con.fetchval(
                        "select bonus_points from players where user_id = $1", user
                    )
                )
            await repo.seed()
            async with db.pool.acquire() as con:
                row = await con.fetchrow(
                    "select shares, spent from stock_holdings where user_id = $1",
                    user,
                )
                after = int(
                    await con.fetchval(
                        "select bonus_points from players where user_id = $1", user
                    )
                )
            assert int(row["shares"]) == 100, "излишек забрали"
            assert int(row["spent"]) == 100000, "потраченное уменьшили пропорционально"
            assert after == before + 50000, "за излишек вернули деньги"
        finally:
            async with db.pool.acquire() as con:
                await con.execute("delete from stock_holdings where user_id = 900012")
                await con.execute("delete from players where user_id = 900012")
            await db.close()

    run(scenario())


def test_stocks_target_moves_smoothly_and_clears():
    async def scenario():
        db = await fresh_db()
        try:
            from app.stocks_repo import StocksRepo

            repo = StocksRepo(db)
            await repo.seed()
            async with db.pool.acquire() as con:
                await con.execute(
                    """
                    update stocks
                       set volatility = 0, price = 1000, alert_price = 1000,
                           target_price = 2000,
                           updated_at = now() - interval '20 seconds'
                     where slug = 'syug'
                    """
                )
            await repo.tick()
            async with db.pool.acquire() as con:
                row = await con.fetchrow(
                    "select price, target_price from stocks where slug = 'syug'"
                )
            assert 1000 < int(row["price"]) <= 1250, "один шаг — без телепорта"
            assert row["target_price"] == 2000, "цель ещё не достигнута"

            for _ in range(30):
                async with db.pool.acquire() as con:
                    await con.execute(
                        "update stocks set updated_at = now() - interval '20 seconds' "
                        "where slug = 'syug'"
                    )
                await repo.tick()
            async with db.pool.acquire() as con:
                row = await con.fetchrow(
                    "select price, target_price from stocks where slug = 'syug'"
                )
            assert int(row["price"]) == 2000, "курс доехал до цели"
            assert row["target_price"] is None, "цель сброшена"
        finally:
            async with db.pool.acquire() as con:
                await con.execute(
                    "update stocks set volatility = 0.03, target_price = null "
                    "where slug = 'syug'"
                )
            await db.close()

    run(scenario())


def test_stocks_tick_reports_growth():
    async def scenario():
        db = await fresh_db()
        try:
            from app.stocks_repo import StocksRepo

            repo = StocksRepo(db)
            await repo.seed()
            # Готовим рост: отметка = старый курс, новый курс на 20% выше,
            # волатильность 0 (шаг не меняет цену), тик «просрочен».
            async with db.pool.acquire() as con:
                await con.execute(
                    """
                    update stocks
                       set volatility = 0,
                           alert_price = price,
                           alerted_at = null,
                           updated_at = now() - interval '1 minute'
                     where slug = 'syug'
                    """
                )
                await con.execute(
                    """
                    update stocks
                       set price = alert_price * 1.2,
                           updated_at = now() - interval '1 minute'
                     where slug = 'syug'
                    """
                )
            alerts = await repo.tick()
            slugs = {a["slug"] for a in alerts}
            assert "syug" in slugs, alerts
            alert = next(a for a in alerts if a["slug"] == "syug")
            assert alert["change"] >= 10
            # повторный тик сразу после оповещения молчит (кулдаун)
            async with db.pool.acquire() as con:
                await con.execute(
                    "update stocks set updated_at = now() - interval '1 minute' "
                    "where slug = 'syug'"
                )
            assert all(a["slug"] != "syug" for a in await repo.tick())
        finally:
            async with db.pool.acquire() as con:
                await con.execute(
                    "update stocks set volatility = 0.03 where slug = 'syug'"
                )
            await db.close()

    run(scenario())


def test_casino_stats_counts_wins_and_losses():
    async def scenario():
        db = await fresh_db()
        try:
            user = 900009
            async with db.pool.acquire() as con:
                await con.execute("delete from casino_log where user_id = $1", user)
                await con.execute("delete from players where user_id = $1", user)
            await db.ensure_player(user, None, "Лудоман")
            async with db.pool.acquire() as con:
                await con.execute(
                    """
                    insert into casino_log
                        (user_id, bet_kind, bet_value, color, rolled, won, outcome, amount)
                    values
                        ($1, 'points', '1000', 'red', 'red', true, 'win', 2000),
                        ($1, 'points', '1000', 'red', 'black', false, 'lose', 333),
                        ($1, 'card', 'daniel', 'green', 'green', true, 'max', 0),
                        ($1, 'card', 'oleg', 'red', 'black', false, 'delete', 0)
                    """,
                    user,
                )
            stats = await db.casino_stats(user)
            assert stats["point_bets"] == 2
            assert stats["staked"] == 2000
            assert stats["returned"] == 2333
            assert stats["won_points"] == 1000
            assert stats["lost_points"] == 667
            assert stats["card_bets"] == 2
            assert stats["card_wins"] == 1
            assert stats["card_deleted"] == 1
        finally:
            async with db.pool.acquire() as con:
                await con.execute("delete from casino_log where user_id = $1", user)
            await db.close()

    run(scenario())


def test_purge_missing_cards_removes_old_entries():
    """Регрессия: удалённая из кода карта оставалась у игрока и ломала профиль."""

    async def scenario():
        db = await fresh_db()
        try:
            user = 900008
            async with db.pool.acquire() as con:
                await con.execute("delete from players where user_id = $1", user)
                await con.execute(
                    """
                    insert into cards (card_id, name, rarity, points, hp, atk,
                                       ability_name, ability_cd, ability)
                    values ('ghost', 'Призрак', 'rare', 1, 1, 1, 'x', 1, '{}'::jsonb)
                    on conflict (card_id) do nothing
                    """
                )
            await db.ensure_player(user, None, "Призрак")
            await db.add_card(user, "ghost")

            await db.purge_missing_cards(["oleg"])

            async with db.pool.acquire() as con:
                left = await con.fetchval(
                    "select count(*) from collection where user_id = $1", user
                )
                ghost = await con.fetchval(
                    "select count(*) from cards where card_id = 'ghost'"
                )
            assert left == 0, "запись у игрока должна исчезнуть"
            assert ghost == 0, "карта-призрак должна исчезнуть из cards"
        finally:
            async with db.pool.acquire() as con:
                await con.execute("delete from collection where card_id = 'ghost'")
                await con.execute("delete from cards where card_id = 'ghost'")
            await db.close()

    run(scenario())
