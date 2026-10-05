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


def test_upgrade_moves_copy_to_inventory_and_can_be_improved_thrice():
    async def scenario():
        db, repo = await fresh()
        try:
            user = 910005
            await reset_users(db, user)
            await prepare(db, user, "Upgrader", ["oleg", "oleg"])

            first = await repo.upgrade_stack(user, "oleg")
            assert first["filled"] == 1
            assert (await db.get_collection(user))["oleg"] == 1

            second = await repo.upgrade_instance(user, first["inventory_id"])
            assert second["filled"] == 2
            third = await repo.upgrade_instance(user, first["inventory_id"])
            assert third["filled"] == 3
            with pytest.raises(MarketError):
                await repo.upgrade_instance(user, first["inventory_id"])

            inventory = await repo.user_inventory(user, include_listed=True)
            assert len(inventory) == 1
            entry = inventory[0]
            card = get_card("oleg")
            stats = effective_stats(card, entry["bonus"])
            assert stats["atk"] >= 1 and stats["hp"] >= 1
            assert 0 <= stats["def"] <= 60
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
