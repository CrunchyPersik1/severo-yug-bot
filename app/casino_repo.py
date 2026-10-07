"""Казино: ставки очками и картами. Всё в транзакциях.

Бонусы казино хранятся отдельно (inventory.casino_bonus) и складываются
с аурами/фонами/эффектами — поэтому влияют и на статы, и на цену.
"""

from __future__ import annotations

import logging
from typing import Any

import asyncpg

from . import casino
from .cards import get_card
from .db import Database, as_json_dict
from .market import market_price
from .market_repo import MarketRepo, bonuses_of


class CasinoError(Exception):
    """Ошибка, которую можно показать игроку."""


log = logging.getLogger(__name__)


class CasinoRepo:
    def __init__(self, db: Database, market: MarketRepo) -> None:
        self.db = db
        self.market = market

    @property
    def pool(self) -> asyncpg.Pool:
        return self.db._p()

    # ------------------------------------------------------------------ #
    # Очки
    # ------------------------------------------------------------------ #

    async def bet_points(self, user_id: int, bet: int, color: str) -> dict[str, Any]:
        bet = int(bet)
        if bet < casino.MIN_BET:
            raise CasinoError(f"Минимальная ставка — {casino.MIN_BET} очков.")
        if bet > casino.MAX_BET:
            raise CasinoError(f"Максимальная ставка — {casino.MAX_BET} очков.")
        rolled = casino.roll_color()
        won = casino.is_win(color, rolled)
        payout = casino.points_win(bet, color) if won else casino.points_lose(bet)

        async with self.pool.acquire() as con:
            async with con.transaction():
                row = await con.fetchrow(
                    """
                    update players set bonus_points = bonus_points - $2
                     where user_id = $1 and bonus_points >= $2
                    returning bonus_points
                    """,
                    user_id,
                    bet,
                )
                if row is None:
                    balance = await con.fetchval(
                        "select coalesce(bonus_points, 0) from players where user_id = $1",
                        user_id,
                    )
                    raise CasinoError(
                        f"Не хватает очков: ставишь {bet}, у тебя {int(balance or 0)}."
                    )
                balance = await con.fetchval(
                    "update players set bonus_points = bonus_points + $2 where user_id = $1 "
                    "returning bonus_points",
                    user_id,
                    payout,
                )
                await con.execute(
                    """
                    insert into casino_log (user_id, bet_kind, bet_value, color, rolled,
                                            won, outcome, amount)
                    values ($1, 'points', $2, $3, $4, $5, $6, $7)
                    """,
                    user_id,
                    str(bet),
                    color,
                    rolled,
                    won,
                    "win" if won else "lose",
                    payout,
                )
        return {
            "kind": "points",
            "bet": bet,
            "color": color,
            "rolled": rolled,
            "won": won,
            "payout": payout,
            "delta": payout - bet,
            "balance": int(balance),
        }

    # ------------------------------------------------------------------ #
    # Карты
    # ------------------------------------------------------------------ #

    async def _as_instance(
        self, con: asyncpg.Connection, user_id: int, unit: dict[str, Any]
    ) -> int:
        """Ставим конкретную копию: если это стак — вынимаем одну в инвентарь."""
        if unit.get("inventory_id") is not None:
            return int(unit["inventory_id"])
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
            raise CasinoError("Карты уже нет в коллекции.")
        await con.execute(
            "delete from collection where user_id = $1 and card_id = $2 and count <= 0",
            user_id,
            unit["card_id"],
        )
        return int(
            await con.fetchval(
                "insert into inventory (user_id, card_id) values ($1, $2) returning id",
                user_id,
                unit["card_id"],
            )
        )

    async def _add_casino_bonus(
        self, con: asyncpg.Connection, inventory_id: int, delta: dict[str, int], absolute: bool = False
    ) -> dict[str, int]:
        current_row = await con.fetchrow(
            "select casino_bonus from inventory where id = $1", int(inventory_id)
        )
        current = as_json_dict(current_row["casino_bonus"]) if current_row else {}
        if absolute:
            final = {stat: int(delta[stat]) for stat in casino.STATS if stat in delta}
        else:
            final = casino.apply_bonus(current, delta)
        await con.execute(
            "update inventory set casino_bonus = $2::jsonb where id = $1",
            int(inventory_id),
            _json(final),
        )
        return final

    async def bet_card(self, user_id: int, unit: dict[str, Any], color: str) -> dict[str, Any]:
        if unit.get("kind") == "case" or not unit.get("card_id"):
            raise CasinoError("Кейс нельзя поставить в казино.")
        card = get_card(unit["card_id"])
        rolled = casino.roll_color()
        won = casino.is_win(color, rolled)
        outcome = "win" if won else "lose"
        fate = None
        offer_id = None
        bonus_after: dict[str, int] = {}

        async with self.pool.acquire() as con:
            async with con.transaction():
                inventory_id = await self._as_instance(con, user_id, unit)

                if won:
                    if color == casino.COLOR_GREEN:
                        delta = {stat: casino.MAX_BONUS[stat] for stat in casino.STATS}
                        bonus_after = await self._add_casino_bonus(
                            con, inventory_id, delta, absolute=True
                        )
                        outcome = "max"
                    else:
                        delta = casino.random_win_bonus()
                        bonus_after = await self._add_casino_bonus(con, inventory_id, delta)
                else:
                    fate = casino.card_fate()
                    if fate == "delete":
                        # снимок и предложение выкупа делаем ДО удаления строки
                        bonus_after = await self._snapshot_before_delete(
                            con, user_id, inventory_id, card
                        )
                        offer_id = await self._make_offer(con, user_id, inventory_id, card)
                        await con.execute(
                            "delete from inventory where id = $1", int(inventory_id)
                        )
                        outcome = "delete"
                    else:
                        delta = casino.random_lose_bonus()
                        bonus_after = await self._add_casino_bonus(con, inventory_id, delta)
                        outcome = "worsen"

                await con.execute(
                    """
                    insert into casino_log (user_id, bet_kind, bet_value, color, rolled,
                                            won, outcome, amount)
                    values ($1, 'card', $2, $3, $4, $5, $6, $7)
                    """,
                    user_id,
                    card.card_id,
                    color,
                    rolled,
                    won,
                    outcome,
                    0,
                )

        return {
            "kind": "card",
            "card": card,
            "color": color,
            "rolled": rolled,
            "won": won,
            "outcome": outcome,
            "fate": fate,
            "inventory_id": inventory_id if fate != "delete" else None,
            "bonus": bonus_after,
            "offer_id": offer_id,
        }

    async def _snapshot_before_delete(
        self, con: asyncpg.Connection, user_id: int, inventory_id: int, card
    ) -> dict[str, int]:
        row = await con.fetchrow(
            "select casino_bonus from inventory where id = $1", int(inventory_id)
        )
        return as_json_dict(row["casino_bonus"]) if row else {}

    async def _make_offer(
        self, con: asyncpg.Connection, user_id: int, inventory_id: int, card
    ) -> int | None:
        """Предложение выкупить проигранную карту — только для редких."""
        if not casino.can_buyback(card.rarity):
            return None
        row = await con.fetchrow(
            """
            select i.casino_bonus, u.aura_id, u.background_id, u.effect_id
              from inventory i
              left join upgrades u on u.inventory_id = i.id
             where i.id = $1
            """,
            int(inventory_id),
        )
        if row is None:
            return None
        upgrades = {
            slot: row[f"{slot}_id"]
            for slot in ("aura", "background", "effect")
            if row[f"{slot}_id"] is not None
        }
        casino_bonus = as_json_dict(row["casino_bonus"])
        bonus = _merge(bonuses_of(upgrades), casino_bonus)
        price = market_price(card, bonus) * casino.BUYBACK_MULT
        return int(
            await con.fetchval(
                """
                insert into casino_lost (user_id, card_id, casino_bonus, upgrades, price,
                                         expires_at)
                values ($1, $2, $3::jsonb, $4::jsonb, $5,
                        now() + make_interval(mins => $6))
                returning id
                """,
                user_id,
                card.card_id,
                _json(casino_bonus),
                _json(upgrades),
                price,
                casino.BUYBACK_MINUTES,
            )
        )

    async def buyback(self, user_id: int, offer_id: int) -> dict[str, Any]:
        async with self.pool.acquire() as con:
            async with con.transaction():
                offer = await con.fetchrow(
                    """
                    select * from casino_lost
                     where id = $1 and user_id = $2 and bought = false and expires_at > now()
                     for update
                    """,
                    int(offer_id),
                    user_id,
                )
                if offer is None:
                    raise CasinoError("Предложение выкупа уже не действует.")
                price = int(offer["price"])
                row = await con.fetchrow(
                    """
                    update players set bonus_points = bonus_points - $2
                     where user_id = $1 and bonus_points >= $2
                    returning bonus_points
                    """,
                    user_id,
                    price,
                )
                if row is None:
                    balance = await con.fetchval(
                        "select coalesce(bonus_points, 0) from players where user_id = $1",
                        user_id,
                    )
                    raise CasinoError(
                        f"Выкуп стоит {price}, а у тебя {int(balance or 0)} очков."
                    )
                card = get_card(offer["card_id"])
                inventory_id = int(
                    await con.fetchval(
                        """
                        insert into inventory (user_id, card_id, casino_bonus)
                        values ($1, $2, $3::jsonb) returning id
                        """,
                        user_id,
                        offer["card_id"],
                        _json(as_json_dict(offer["casino_bonus"])),
                    )
                )
                upgrades = as_json_dict(offer["upgrades"])
                if upgrades:
                    await con.execute(
                        """
                        insert into upgrades (inventory_id, aura_id, background_id, effect_id)
                        values ($1, $2, $3, $4)
                        """,
                        inventory_id,
                        upgrades.get("aura"),
                        upgrades.get("background"),
                        upgrades.get("effect"),
                    )
                await con.execute(
                    "update casino_lost set bought = true where id = $1", int(offer_id)
                )
        return {
            "card": card,
            "price": price,
            "balance": int(row["bonus_points"]),
            "inventory_id": inventory_id,
        }

    async def offer(self, offer_id: int) -> dict[str, Any] | None:
        async with self.pool.acquire() as con:
            row = await con.fetchrow("select * from casino_lost where id = $1", int(offer_id))
        return dict(row) if row else None


def _json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def _merge(first: dict[str, int], second: dict[str, int]) -> dict[str, int]:
    result = dict(first or {})
    for stat, amount in (second or {}).items():
        result[stat] = result.get(stat, 0) + int(amount)
    return {stat: value for stat, value in result.items() if value}
