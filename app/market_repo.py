"""Транзакционные операции рынка, инвентаря и улучшений на asyncpg.

Всё, что меняет очки или владельца карты, выполняется в одной транзакции:
покупка не может списать очки и не отдать карту.
"""

from __future__ import annotations

import logging
from typing import Any

import asyncpg

from .cards import CARDS_BY_ID, get_card
from .cases import CASE_PRICE
from .db import Database
from .items import BY_SLOT, Item, SLOTS, SLOT_ICONS, SLOT_TITLES, TABLE_BY_SLOT, roll_slot, seed_rows
from .market import (
    HONEST_GAIN_PER_DAY,
    MARKET_FEE,
    UPGRADE_PRICE,
    can_sell,
    clamp_rating,
    effective_stats,
    is_honest_deal,
    listing_penalty,
    market_fee,
    market_price,
    price_ratio,
    seller_income,
    sum_bonus,
)

log = logging.getLogger(__name__)


class MarketError(Exception):
    """Ошибка, которую можно показать пользователю."""


ITEMS_BY_SLOT: dict[str, dict[int, Item]] = {
    slot: {item.id: item for item in BY_SLOT[slot]} for slot in SLOTS
}


def item_of(slot: str, item_id: int | None) -> Item | None:
    if item_id is None:
        return None
    return ITEMS_BY_SLOT[slot].get(int(item_id))


def bonuses_of(upgrades: dict[str, Any] | None) -> dict[str, int]:
    """Суммарный процент от ауры + фона + эффекта."""
    if not upgrades:
        return {}
    return sum_bonus(
        *[
            (item_of(slot, upgrades.get(f"{slot}_id")).bonus if item_of(slot, upgrades.get(f"{slot}_id")) else None)
            for slot in SLOTS
        ]
    )


def unit_reference_price(unit: dict[str, Any], bonus: dict[str, int] | None = None) -> int:
    """Рыночная цена юнита: кейс стоит фиксированно, карта — по редкости и улучшениям."""
    if unit.get("kind") == "case":
        return CASE_PRICE
    return market_price(get_card(unit["card_id"]), bonus)


class MarketRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    @property
    def pool(self) -> asyncpg.Pool:
        return self.db._p()

    # ------------------------------------------------------------------ #
    # Справочник улучшений
    # ------------------------------------------------------------------ #

    async def seed_items(self) -> None:
        async with self.pool.acquire() as con:
            for table, rows in seed_rows():
                await con.executemany(
                    f"""
                    insert into {table} (id, name, stat_bonus)
                    values ($1, $2, $3::jsonb)
                    on conflict (id) do update set name = excluded.name,
                                                   stat_bonus = excluded.stat_bonus
                    """,
                    rows,
                )
            for slot in SLOTS:
                table = TABLE_BY_SLOT[slot]
                await con.execute(
                    f"select setval(pg_get_serial_sequence('{table}', 'id'), "
                    f"(select coalesce(max(id), 1) from {table}))"
                )

    # ------------------------------------------------------------------ #
    # Покупка юнита: стак из collection или конкретная копия из inventory
    # ------------------------------------------------------------------ #

    async def owned_unit(self, user_id: int, handle: tuple[str, Any]) -> dict[str, Any]:
        kind, value = handle
        async with self.pool.acquire() as con:
            if kind == "case":
                row = await con.fetchrow(
                    """
                    select id from cases
                     where id = $1 and user_id = $2 and listed = false and opened = false
                    """,
                    int(value),
                    user_id,
                )
                if row is None:
                    raise MarketError(f"Кейса #{value} у тебя нет.")
                return {
                    "kind": "case",
                    "card_id": None,
                    "inventory_id": None,
                    "case_id": int(row["id"]),
                }
            if kind == "inventory":
                row = await con.fetchrow(
                    "select id, card_id, listed from inventory where id = $1 and user_id = $2",
                    int(value),
                    user_id,
                )
                if row is None:
                    raise MarketError(f"Улучшенной карты #{value} у тебя нет.")
                if row["listed"]:
                    raise MarketError(f"Карта #{value} уже выставлена на продажу.")
                return {
                    "kind": "inventory",
                    "card_id": row["card_id"],
                    "inventory_id": int(row["id"]),
                    "case_id": None,
                }

            row = await con.fetchrow(
                "select count from collection where user_id = $1 and card_id = $2",
                user_id,
                str(value),
            )
            if row is None or int(row["count"]) < 1:
                raise MarketError(f"Карты #{value} у тебя нет.")
            if str(value) not in CARDS_BY_ID:
                raise MarketError(f"Карты #{value} не существует.")
            return {
                "kind": "card",
                "card_id": str(value),
                "inventory_id": None,
                "case_id": None,
            }

    async def unit_bonus(self, inventory_id: int | None) -> dict[str, int]:
        if inventory_id is None:
            return {}
        async with self.pool.acquire() as con:
            row = await con.fetchrow("select * from upgrades where inventory_id = $1", inventory_id)
        return bonuses_of(dict(row) if row else None)

    # ------------------------------------------------------------------ #
    # Репутация
    # ------------------------------------------------------------------ #

    async def _apply_rating(self, con: asyncpg.Connection, user_id: int, delta: float) -> float:
        """Меняет репутацию с учётом суточного лимита на рост."""
        row = await con.fetchrow(
            "select rating, rating_day, rating_today from players where user_id = $1 for update",
            user_id,
        )
        if row is None:
            return 0.0
        today = await con.fetchval("select current_date")
        gained_today = float(row["rating_today"]) if row["rating_day"] == today else 0.0

        applied = float(delta)
        if applied > 0:
            room = HONEST_GAIN_PER_DAY - gained_today
            applied = max(0.0, min(applied, room))
        new_rating = clamp_rating(float(row["rating"]) + applied)
        new_gained = gained_today + applied if applied > 0 else gained_today

        await con.execute(
            """
            update players
               set rating = $2::numeric,
                   rating_day = $3,
                   rating_today = $4::numeric
             where user_id = $1
            """,
            user_id,
            new_rating,
            today,
            round(new_gained, 2),
        )
        return new_rating

    async def find_by_username(self, username: str) -> dict[str, Any] | None:
        clean = (username or "").lstrip("@").strip()
        if not clean:
            return None
        async with self.pool.acquire() as con:
            row = await con.fetchrow(
                "select user_id, first_name, username from players where lower(username) = lower($1)",
                clean,
            )
        return dict(row) if row else None

    async def balance(self, user_id: int) -> int:
        async with self.pool.acquire() as con:
            value = await con.fetchval(
                "select coalesce(bonus_points, 0) from players where user_id = $1", user_id
            )
        return int(value or 0)

    async def rating_profile(self, user_id: int) -> dict[str, Any] | None:
        async with self.pool.acquire() as con:
            row = await con.fetchrow(
                "select user_id, first_name, username, rating, rating_day, rating_today "
                "from players where user_id = $1",
                user_id,
            )
            if row is None:
                return None
            today = await con.fetchval("select current_date")
        profile = dict(row)
        profile["rating"] = float(profile["rating"])
        profile["gained_today"] = (
            float(profile["rating_today"]) if profile["rating_day"] == today else 0.0
        )
        return profile

    async def rating_info(self, user_id: int) -> dict[str, Any]:
        async with self.pool.acquire() as con:
            row = await con.fetchrow(
                "select rating, rating_day, rating_today from players where user_id = $1", user_id
            )
            today = await con.fetchval("select current_date")
        if row is None:
            return {"rating": 5.0, "gained_today": 0.0}
        gained = float(row["rating_today"]) if row["rating_day"] == today else 0.0
        return {"rating": float(row["rating"]), "gained_today": gained}

    # ------------------------------------------------------------------ #
    # Лоты
    # ------------------------------------------------------------------ #

    async def create_lot(
        self, seller_id: int, unit: dict[str, Any], price: int
    ) -> dict[str, Any]:
        bonus = await self.unit_bonus(unit.get("inventory_id"))
        reference = unit_reference_price(unit, bonus)

        info = await self.rating_info(seller_id)
        if not can_sell(info["rating"]):
            raise MarketError(
                f"Репутация {info['rating']:.2f} — ниже {1.5}. Выставлять лоты нельзя."
            )

        penalty, suspect = listing_penalty(price_ratio(price, reference))

        async with self.pool.acquire() as con:
            async with con.transaction():
                await self._take_unit(con, seller_id, unit)

                lot = await con.fetchrow(
                    """
                    insert into market (seller_id, card_id, inventory_id, case_id,
                                        kind, price, market_price, suspect)
                    values ($1, $2, $3, $4, $5, $6, $7, $8)
                    returning *
                    """,
                    seller_id,
                    unit["card_id"],
                    unit["inventory_id"],
                    unit["case_id"],
                    unit.get("kind", "card"),
                    int(price),
                    int(reference),
                    suspect,
                )

                if penalty:
                    await self._apply_rating(con, seller_id, penalty)

        result = dict(lot)
        result.update(
            {
                "reference": reference,
                "bonus": bonus,
                "penalty": penalty,
                "suspect": suspect,
                "ratio": price_ratio(price, reference),
            }
        )
        return result

    async def get_lot(self, lot_id: int) -> dict[str, Any] | None:
        async with self.pool.acquire() as con:
            row = await con.fetchrow(
                """
                select m.*, p.first_name, p.username, p.rating,
                       u.aura_id, u.background_id, u.effect_id
                  from market m
                  join players p on p.user_id = m.seller_id
                  left join upgrades u on u.inventory_id = m.inventory_id
                 where m.id = $1
                """,
                int(lot_id),
            )
        if row is None:
            return None
        lot = dict(row)
        lot["bonus"] = await self.unit_bonus(lot["inventory_id"])
        if not lot["market_price"]:
            lot["market_price"] = market_price(get_card(lot["card_id"]), lot["bonus"])
        return lot

    async def list_lots(self, limit: int = 6, offset: int = 0) -> list[dict[str, Any]]:
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                """
                select m.*, p.first_name, p.username, p.rating,
                       u.aura_id, u.background_id, u.effect_id
                  from market m
                  join players p on p.user_id = m.seller_id
                  left join upgrades u on u.inventory_id = m.inventory_id
                 where m.status = 'active'
                 order by m.created_at desc
                 limit $1 offset $2
                """,
                limit,
                offset,
            )
        lots = []
        for row in rows:
            lot = dict(row)
            lot["bonus"] = await self.unit_bonus(lot["inventory_id"])
            lots.append(lot)
        return lots

    async def count_lots(self) -> int:
        async with self.pool.acquire() as con:
            return int(await con.fetchval("select count(*) from market where status = 'active'"))

    async def seller_lots(self, seller_id: int, limit: int = 20) -> list[dict[str, Any]]:
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                """
                select m.*, u.aura_id, u.background_id, u.effect_id
                  from market m
                  left join upgrades u on u.inventory_id = m.inventory_id
                 where m.seller_id = $1 and m.status = 'active'
                 order by m.id
                 limit $2
                """,
                seller_id,
                limit,
            )
        return [dict(r) for r in rows]

    async def rating_board(self, limit: int = 10) -> list[dict[str, Any]]:
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                """
                select p.user_id, p.first_name, p.username, p.rating,
                       (select count(*) from history h
                         where h.buyer_id = p.user_id or h.seller_id = p.user_id) as deals
                  from players p
                 where p.rating <> 5.0
                 order by p.rating desc
                 limit $1
                """,
                limit,
            )
        return [dict(r) for r in rows]

    async def deal_stats(self, user_id: int) -> dict[str, int]:
        async with self.pool.acquire() as con:
            deals = await con.fetchval(
                "select count(*) from history where buyer_id = $1 or seller_id = $1", user_id
            )
            gifts = await con.fetchval("select count(*) from gifts where sender_id = $1", user_id)
        return {"deals": int(deals or 0), "gifts": int(gifts or 0)}

    async def cancel_lot(self, lot_id: int, seller_id: int) -> dict[str, Any]:
        async with self.pool.acquire() as con:
            async with con.transaction():
                lot = await con.fetchrow(
                    "select * from market where id = $1 for update", int(lot_id)
                )
                if lot is None:
                    raise MarketError("Лот не найден.")
                if lot["seller_id"] != seller_id:
                    raise MarketError("Это не твой лот.")
                if lot["status"] != "active":
                    raise MarketError("Лот уже не активен.")
                await self._give_unit(con, seller_id, dict(lot))
                await con.execute(
                    "update market set status = 'cancelled', updated_at = now() where id = $1",
                    int(lot_id),
                )
        return dict(lot)

    async def change_price(self, lot_id: int, seller_id: int, price: int) -> dict[str, Any]:
        async with self.pool.acquire() as con:
            lot = await con.fetchrow("select * from market where id = $1", int(lot_id))
            if lot is None:
                raise MarketError("Лот не найден.")
            if lot["seller_id"] != seller_id:
                raise MarketError("Это не твой лот.")
            if lot["status"] != "active":
                raise MarketError("Лот уже не активен.")
            bonus = await self.unit_bonus(lot["inventory_id"])
            reference = unit_reference_price(dict(lot), bonus)
            penalty, suspect = listing_penalty(price_ratio(price, reference))
            async with con.transaction():
                await con.execute(
                    """
                    update market
                       set price = $2, market_price = $3, suspect = $4, updated_at = now()
                     where id = $1
                    """,
                    int(lot_id),
                    int(price),
                    int(reference),
                    suspect,
                )
                if penalty:
                    await self._apply_rating(con, seller_id, penalty)
        updated = dict(lot)
        updated.update({"price": int(price), "market_price": reference, "suspect": suspect})
        return updated

    async def _take_unit(
        self, con: asyncpg.Connection, user_id: int, unit: dict[str, Any]
    ) -> None:
        """Забирает юнит у игрока в эскроу лота."""
        if unit.get("case_id") is not None:
            row = await con.fetchrow(
                """
                update cases set listed = true
                 where id = $1 and user_id = $2 and listed = false and opened = false
                returning id
                """,
                int(unit["case_id"]),
                user_id,
            )
            if row is None:
                raise MarketError("Этот кейс уже нельзя выставить.")
            return

        if unit.get("inventory_id") is None:
            row = await con.fetchrow(
                """
                update collection set count = count - 1
                 where user_id = $1 and card_id = $2 and count > 0
                returning count
                """,
                user_id,
                unit["card_id"],
            )
            if row is None:
                raise MarketError("Карты уже нет в коллекции.")
            await con.execute(
                "delete from collection where user_id = $1 and card_id = $2 and count <= 0",
                user_id,
                unit["card_id"],
            )
            return

        row = await con.fetchrow(
            """
            update inventory set listed = true
             where id = $1 and user_id = $2 and listed = false
            returning id
            """,
            int(unit["inventory_id"]),
            user_id,
        )
        if row is None:
            raise MarketError("Эту копию уже нельзя выставить.")

    async def _give_unit(
        self, con: asyncpg.Connection, user_id: int, unit: dict[str, Any]
    ) -> None:
        """Отдаёт юнит игроку (покупка, снятие лота, подарок)."""
        if unit.get("case_id") is not None:
            await con.execute(
                "update cases set user_id = $2, listed = false where id = $1",
                int(unit["case_id"]),
                user_id,
            )
            return
        if unit.get("inventory_id") is not None:
            await con.execute(
                "update inventory set user_id = $2, listed = false where id = $1",
                int(unit["inventory_id"]),
                user_id,
            )
            return
        await con.execute(
            """
            insert into collection (user_id, card_id, count) values ($1, $2, 1)
            on conflict (user_id, card_id) do update set count = collection.count + 1
            """,
            user_id,
            unit["card_id"],
        )

    # ------------------------------------------------------------------ #
    # Покупка
    # ------------------------------------------------------------------ #

    async def buy_lot(self, lot_id: int, buyer_id: int) -> dict[str, Any]:
        async with self.pool.acquire() as con:
            async with con.transaction():
                lot = await con.fetchrow(
                    "select m.*, p.first_name as seller_name from market m "
                    "join players p on p.user_id = m.seller_id "
                    "where m.id = $1 for update of m",
                    int(lot_id),
                )
                if lot is None:
                    raise MarketError("Лот не найден.")
                if lot["status"] != "active":
                    raise MarketError("Лот уже продан или снят.")
                if lot["seller_id"] == buyer_id:
                    raise MarketError("Нельзя купить свой лот.")

                price = int(lot["price"])
                balance = await con.fetchrow(
                    "select bonus_points from players where user_id = $1 for update", buyer_id
                )
                if balance is None:
                    raise MarketError("Профиль не найден.")
                if int(balance["bonus_points"]) < price:
                    raise MarketError(
                        f"Не хватает очков: нужно {price}, у тебя {int(balance['bonus_points'])}."
                    )

                fee = market_fee(price)
                income = seller_income(price)

                await con.execute(
                    "update players set bonus_points = bonus_points - $2 where user_id = $1",
                    buyer_id,
                    price,
                )
                await con.execute(
                    "update players set bonus_points = bonus_points + $2 where user_id = $1",
                    lot["seller_id"],
                    income,
                )

                await self._give_unit(con, buyer_id, dict(lot))
                await con.execute(
                    "update market set status = 'sold', updated_at = now() where id = $1",
                    int(lot_id),
                )
                await con.execute(
                    """
                    insert into history (buyer_id, seller_id, card_id, kind, price, fee)
                    values ($1, $2, $3, $4, $5, $6)
                    """,
                    buyer_id,
                    lot["seller_id"],
                    lot["card_id"],
                    lot["kind"],
                    price,
                    fee,
                )

                reference = int(lot["market_price"]) or unit_reference_price(
                    dict(lot), await self.unit_bonus(lot["inventory_id"])
                )
                honest = is_honest_deal(price, reference)
                new_rating = None
                if honest:
                    new_rating = await self._apply_rating(con, lot["seller_id"], 0.1)

        return {
            "lot_id": int(lot_id),
            "kind": lot["kind"],
            "card_id": lot["card_id"],
            "case_id": lot["case_id"],
            "price": price,
            "fee": fee,
            "income": income,
            "honest": honest,
            "seller_id": lot["seller_id"],
            "seller_rating": new_rating,
        }

    # ------------------------------------------------------------------ #
    # Подарки
    # ------------------------------------------------------------------ #

    async def gift_card(self, sender_id: int, unit: dict[str, Any], receiver_id: int) -> None:
        if sender_id == receiver_id:
            raise MarketError("Нельзя подарить самому себе.")
        async with self.pool.acquire() as con:
            async with con.transaction():
                await self._take_unit(con, sender_id, unit)
                await self._ensure_player(con, receiver_id)
                await self._give_unit(con, receiver_id, unit)
                await con.execute(
                    """
                    insert into gifts (sender_id, receiver_id, card_id, inventory_id, kind)
                    values ($1, $2, $3, $4, $5)
                    """,
                    sender_id,
                    receiver_id,
                    unit["card_id"],
                    unit["inventory_id"],
                    unit.get("kind", "card"),
                )

    async def _ensure_player(self, con: asyncpg.Connection, user_id: int) -> None:
        await con.execute(
            "insert into players (user_id) values ($1) on conflict (user_id) do nothing", user_id
        )

    # ------------------------------------------------------------------ #
    # Улучшения
    # ------------------------------------------------------------------ #

    async def _charge(self, con: asyncpg.Connection, user_id: int, amount: int) -> int:
        """Списывает очки; если не хватает — транзакция откатится."""
        row = await con.fetchrow(
            """
            update players set bonus_points = bonus_points - $2
             where user_id = $1 and bonus_points >= $2
            returning bonus_points
            """,
            user_id,
            int(amount),
        )
        if row is None:
            balance = await con.fetchval(
                "select coalesce(bonus_points, 0) from players where user_id = $1", user_id
            )
            raise MarketError(
                f"Не хватает очков: улучшение стоит {int(amount)}, у тебя {int(balance or 0)}."
            )
        return int(row["bonus_points"])

    async def upgrade_stack(self, user_id: int, card_id: str) -> dict[str, Any]:
        """Копия уходит из стака в inventory и сразу получает все три улучшения."""
        async with self.pool.acquire() as con:
            async with con.transaction():
                await self._charge(con, user_id, UPGRADE_PRICE)
                row = await con.fetchrow(
                    """
                    update collection set count = count - 1
                     where user_id = $1 and card_id = $2 and count > 0
                    returning count
                    """,
                    user_id,
                    card_id,
                )
                if row is None:
                    raise MarketError(f"Карты #{card_id} у тебя нет.")
                await con.execute(
                    "delete from collection where user_id = $1 and card_id = $2 and count <= 0",
                    user_id,
                    card_id,
                )
                inventory_id = await con.fetchval(
                    "insert into inventory (user_id, card_id) values ($1, $2) returning id",
                    user_id,
                    card_id,
                )
                items = {slot: self._roll_item(slot) for slot in SLOTS}
                await con.execute(
                    """
                    insert into upgrades (inventory_id, aura_id, background_id, effect_id)
                    values ($1, $2, $3, $4)
                    """,
                    int(inventory_id),
                    items["aura"].id,
                    items["background"].id,
                    items["effect"].id,
                )
                balance = await con.fetchval(
                    "select bonus_points from players where user_id = $1", user_id
                )
        return {
            "inventory_id": int(inventory_id),
            "card_id": card_id,
            "items": items,
            "balance": int(balance),
        }

    async def upgrade_instance(self, user_id: int, inventory_id: int) -> dict[str, Any]:
        """Досдает недостающие слоты (нужно для копий, улучшенных до этого правила)."""
        async with self.pool.acquire() as con:
            async with con.transaction():
                row = await con.fetchrow(
                    "select * from inventory where id = $1 and user_id = $2 for update",
                    int(inventory_id),
                    user_id,
                )
                if row is None:
                    raise MarketError(f"Копии #{inventory_id} у тебя нет.")
                if row["listed"]:
                    raise MarketError("Копия выставлена на продажу.")
                current = await con.fetchrow(
                    "select * from upgrades where inventory_id = $1", int(inventory_id)
                )
                filled = {
                    slot: (current[slot + "_id"] if current is not None else None)
                    for slot in SLOTS
                }
                free = [slot for slot in SLOTS if filled[slot] is None]
                if not free:
                    raise MarketError(
                        "У карты уже есть аура, фон и эффект — улучшать больше нечего."
                    )
                await self._charge(con, user_id, UPGRADE_PRICE)
                items = {slot: self._roll_item(slot) for slot in free}
                if current is None:
                    await con.execute(
                        "insert into upgrades (inventory_id) values ($1)", int(inventory_id)
                    )
                for slot, item in items.items():
                    await con.execute(
                        f"update upgrades set {slot}_id = $2 where inventory_id = $1",
                        int(inventory_id),
                        item.id,
                    )
                balance = await con.fetchval(
                    "select bonus_points from players where user_id = $1", user_id
                )
        return {
            "inventory_id": int(inventory_id),
            "card_id": row["card_id"],
            "items": items,
            "balance": int(balance),
        }

    async def user_inventory(self, user_id: int, include_listed: bool = False) -> list[dict[str, Any]]:
        query = """
            select i.id, i.card_id, i.listed,
                   u.aura_id, u.background_id, u.effect_id
              from inventory i
              left join upgrades u on u.inventory_id = i.id
             where i.user_id = $1
        """
        if not include_listed:
            query += " and i.listed = false"
        query += " order by i.id"
        async with self.pool.acquire() as con:
            rows = await con.fetch(query, user_id)
        out = []
        for row in rows:
            item = dict(row)
            item["bonus"] = bonuses_of(item)
            out.append(item)
        return out