"""Интеграционные тесты рынка на живом Postgres (в CI поднимается контейнер)."""

from __future__ import annotations

import asyncio
import os

import pytest

from app.cards import card_rows, get_card
from app.db import Database
from app.market import effective_stats, market_price
from app.market_repo import MarketError, MarketRepo

DSN = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL не задан")


async def fresh():
    db = Database(DSN or "")
    await db.connect()
    await db.init_schema()
    await db.upsert_cards(card_rows())
    repo = MarketRepo(db)
    await repo.seed_items()
    return db, repo


async def reset_users(db, *user_ids: int) -> None:
    async with db.pool.acquire() as con:
        await con.execute(
            "delete from history where seller_id = any($1::bigint[]) or buyer_id = any($1::bigint[])",
            list(user_ids),
        )
        await con.execute(
            "delete from gifts where sender_id = any($1::bigint[]) or receiver_id = any($1::bigint[])",
            list(user_ids),
        )
        await con.execute("delete from players where user_id = any($1::bigint[])", list(user_ids))


async def prepare(db, user_id: int, name: str, cards: list[str], balance: int = 0) -> None:
    await db.ensure_player(user_id, None, name)
    for card_id in cards:
        await db.add_card(user_id, card_id)
    async with db.pool.acquire() as con:
        await con.execute(
            "update players set bonus_points = $2 where user_id = $1", user_id, balance
        )


def test_item_catalogue_is_seeded():
    async def scenario():
        db, repo = await fresh()
        try:
            async with db.pool.acquire() as con:
                for table in ("auras", "backgrounds", "effects"):
                    assert await con.fetchval(f"select count(*) from {table}") == 10
        finally:
            await db.close()

    asyncio.run(scenario())


def test_market_full_cycle_transfers_card_and_points():
    async def scenario():
        db, repo = await fresh()
        try:
            seller, buyer = 910001, 910002
            await reset_users(db, seller, buyer)
            await prepare(db, seller, "Seller", ["oleg"])
            await prepare(db, buyer, "Buyer", [], balance=5000)

            unit = await repo.owned_unit(seller, ("card", "oleg"))
            lot = await repo.create_lot(seller, unit, 400)
            assert lot["suspect"] is False
            assert lot["reference"] == market_price(get_card("oleg"))
            assert await db.get_collection(seller) == {}, "карта должна уйти в эскроу"

            result = await repo.buy_lot(lot["id"], buyer)
            assert result["fee"] == 20 and result["income"] == 380
            assert result["honest"] is True
            assert (await db.get_collection(buyer))["oleg"] == 1
            assert await repo.balance(buyer) == 4600
            assert await repo.balance(seller) == 380
            assert (await repo.rating_info(seller))["rating"] == 5.1
        finally:
            await db.close()

    asyncio.run(scenario())


def test_dumping_marks_lot_and_hurts_rating():
    async def scenario():
        db, repo = await fresh()
        try:
            seller = 910003
            await reset_users(db, seller)
            await prepare(db, seller, "Dumper", ["valeriya"])  # 15000 * 4 = 60000

            unit = await repo.owned_unit(seller, ("card", "valeriya"))
            dirt = await repo.create_lot(seller, unit, 5000)  # 8% от рыночной
            assert dirt["suspect"] is True
            assert dirt["penalty"] == -1.0
            assert (await repo.rating_info(seller))["rating"] == 4.0

            await repo.cancel_lot(dirt["id"], seller)
            assert (await db.get_collection(seller))["valeriya"] == 1

            unit = await repo.owned_unit(seller, ("card", "valeriya"))
            cheap = await repo.create_lot(seller, unit, 20000)  # 33% от рыночной
            assert cheap["suspect"] is False
            assert cheap["penalty"] == -0.5
            assert (await repo.rating_info(seller))["rating"] == 3.5
        finally:
            await db.close()

    asyncio.run(scenario())


def test_low_rating_blocks_listing():
    async def scenario():
        db, repo = await fresh()
        try:
            seller = 910004
            await reset_users(db, seller)
            await prepare(db, seller, "Bad", ["oleg"])
            async with db.pool.acquire() as con:
                await con.execute("update players set rating = 1.0 where user_id = $1", seller)
            unit = await repo.owned_unit(seller, ("card", "oleg"))
            with pytest.raises(MarketError):
                await repo.create_lot(seller, unit, 100)
            assert (await db.get_collection(seller)).get("oleg") == 1, "карта не должна пропасть"
        finally:
            await db.close()

    asyncio.run(scenario())


def test_upgrade_costs_points_and_gives_all_three_slots_at_once():
    async def scenario():
        db, repo = await fresh()
        try:
            user = 910005
            await reset_users(db, user)
            await prepare(db, user, "Upgrader", ["oleg", "oleg"], balance=2000)

            outcome = await repo.upgrade_stack(user, "oleg")
            assert set(outcome["items"]) == {"aura", "background", "effect"}
            assert outcome["balance"] == 2000 - 750
            assert (await db.get_collection(user))["oleg"] == 1

            inventory = await repo.user_inventory(user, include_listed=True)
            assert len(inventory) == 1
            entry = inventory[0]
            assert entry["aura_id"] and entry["background_id"] and entry["effect_id"]

            card = get_card("oleg")
            stats = effective_stats(card, entry["bonus"])
            assert stats["atk"] >= 1 and stats["hp"] >= 1
            assert 0 <= stats["def"] <= 60

            # повторно улучшить ту же копию нельзя, и очки не списываются
            with pytest.raises(MarketError):
                await repo.upgrade_instance(user, outcome["inventory_id"])
            assert await repo.balance(user) == 1250
        finally:
            await db.close()

    asyncio.run(scenario())


def test_upgrade_needs_money_and_keeps_the_card():
    async def scenario():
        db, repo = await fresh()
        try:
            user = 910014
            await reset_users(db, user)
            await prepare(db, user, "Poor", ["oleg"], balance=100)

            with pytest.raises(MarketError):
                await repo.upgrade_stack(user, "oleg")

            assert await repo.balance(user) == 100, "неудачная попытка не списывает очки"
            assert (await db.get_collection(user))["oleg"] == 1, "карта остаётся в коллекции"
            assert await repo.user_inventory(user, include_listed=True) == []
        finally:
            await db.close()

    asyncio.run(scenario())


def test_gift_moves_card_and_writes_history():
    async def scenario():
        db, repo = await fresh()
        try:
            sender, receiver = 910006, 910007
            await reset_users(db, sender, receiver)
            await prepare(db, sender, "Sender", ["karina"])
            await prepare(db, receiver, "Receiver", [])

            unit = await repo.owned_unit(sender, ("card", "karina"))
            await repo.gift_card(sender, unit, receiver)
            assert await db.get_collection(sender) == {}
            assert (await db.get_collection(receiver))["karina"] == 1
            async with db.pool.acquire() as con:
                assert await con.fetchval("select count(*) from gifts where sender_id = $1", sender) == 1
        finally:
            await db.close()

    asyncio.run(scenario())


def test_buying_own_lot_and_insufficient_funds_are_blocked():
    async def scenario():
        db, repo = await fresh()
        try:
            poor, seller = 910008, 910009
            await reset_users(db, poor, seller)
            await prepare(db, seller, "Seller", ["oleg"])
            await prepare(db, poor, "Poor", [], balance=10)

            unit = await repo.owned_unit(seller, ("card", "oleg"))
            lot = await repo.create_lot(seller, unit, 400)

            with pytest.raises(MarketError):
                await repo.buy_lot(lot["id"], seller)
            with pytest.raises(MarketError):
                await repo.buy_lot(lot["id"], poor)

            # лот остался жив и карта всё ещё в эскроу
            still = await repo.get_lot(lot["id"])
            assert still is not None and still["status"] == "active"
            assert await db.get_collection(seller) == {}
        finally:
            await db.close()

    asyncio.run(scenario())

def test_case_can_be_sold_and_bought_on_market():
    async def scenario():
        db, repo = await fresh()
        try:
            seller, buyer = 910010, 910011
            await reset_users(db, seller, buyer)
            await prepare(db, seller, "CaseSeller", [], balance=0)
            await prepare(db, buyer, "CaseBuyer", [], balance=20000)

            case_id = await db.add_case(seller, "roulette")
            assert len(await db.user_cases(seller)) == 1

            unit = await repo.owned_unit(seller, ("case", case_id))
            lot = await repo.create_lot(seller, unit, 6000)
            assert lot["reference"] == 5000, "рыночная цена кейса фиксирована"
            assert await db.user_cases(seller) == [], "кейс уходит в эскроу"

            result = await repo.buy_lot(lot["id"], buyer)
            assert result["kind"] == "case"
            assert result["fee"] == 300 and result["income"] == 5700
            assert await repo.balance(buyer) == 14000
            assert await repo.balance(seller) == 5700

            cases = await db.user_cases(buyer)
            assert len(cases) == 1 and cases[0]["id"] == case_id
            assert await db.open_case(buyer, case_id) is True
            # открытый кейс пропадает из списка, но остаётся в истории
            assert await db.user_cases(buyer) == []
            history = await db.user_cases(buyer, include_opened=True)
            assert len(history) == 1 and history[0]["opened"] is True
            # и повторно его не открыть
            assert await db.open_case(buyer, case_id) is False
        finally:
            await db.close()

    asyncio.run(scenario())


def test_cancelled_case_lot_returns_the_case():
    async def scenario():
        db, repo = await fresh()
        try:
            seller = 910012
            await reset_users(db, seller)
            await prepare(db, seller, "CaseCancel", [], balance=0)
            case_id = await db.add_case(seller, "roulette")
            unit = await repo.owned_unit(seller, ("case", case_id))
            lot = await repo.create_lot(seller, unit, 5000)
            assert await db.user_cases(seller) == []
            await repo.cancel_lot(lot["id"], seller)
            back = await db.user_cases(seller)
            assert len(back) == 1 and back[0]["id"] == case_id
        finally:
            await db.close()

    asyncio.run(scenario())


def test_roulette_limit_is_once_a_day():
    async def scenario():
        db, repo = await fresh()
        try:
            user = 910013
            await reset_users(db, user)
            await prepare(db, user, "Spinner", [])
            from datetime import timedelta

            from app.roulette import roulette_day_key

            today = roulette_day_key()
            assert await db.claim_roulette(user, today) is True
            assert await db.claim_roulette(user, today) is False
            assert await db.claim_roulette(user, today + timedelta(days=1)) is True
        finally:
            await db.close()

    asyncio.run(scenario())