"""Магазин: то, что продаёт сама игра — учителя, наборы и аксессуары.

Цены считаются ТОЛЬКО на сервере: с клиента приходит лишь sku, иначе
любой мог бы купить учителя за один балл.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import asyncpg

from .cards import CARDS, get_card
from .db import Database
from .items import ACCESSORIES, Item
from .market import market_price
from .market_repo import MarketRepo

log = logging.getLogger(__name__)

PACK_AUTUMN_SKU = "pack:autumn"
PACK_AUTUMN_PRICE = 200_000
PACK_AUTUMN_CARDS: tuple[str, ...] = ("misya", "misha")
PACK_AUTUMN_ACCESSORY = 1  # Сердечко

ACCESSORY_PRICE = 60_000


class ShopError(Exception):
    """Ошибку можно показать игроку."""


@dataclass(frozen=True)
class ShopEntry:
    sku: str
    kind: str  # card | pack | accessory
    title: str
    subtitle: str
    price: int
    payload: dict[str, Any]


def accessory_item(item_id: int) -> Item:
    for item in ACCESSORIES:
        if item.id == item_id:
            return item
    raise ShopError(f"Аксессуара {item_id} нет.")


def catalog() -> list[ShopEntry]:
    """Весь ассортимент. Учителя — по возрастанию цены."""
    entries: list[ShopEntry] = []
    for card in CARDS:
        if card.rarity != "teacher":
            continue
        entries.append(
            ShopEntry(
                sku=f"card:{card.card_id}",
                kind="card",
                title=card.display_name,
                subtitle=f"{card.ability.name} · урон по способности "
                f"{card.ability.effects.get('damage', 0)}",
                price=market_price(card),
                payload={"card_id": card.card_id},
            )
        )
    entries.sort(key=lambda entry: entry.price)

    pack_names = " + ".join(get_card(cid).display_name for cid in PACK_AUTUMN_CARDS)
    entries.append(
        ShopEntry(
            sku=PACK_AUTUMN_SKU,
            kind="pack",
            title="Осенний набор",
            subtitle=f"{pack_names} и Сердечко для Миши",
            price=PACK_AUTUMN_PRICE,
            payload={
                "cards": list(PACK_AUTUMN_CARDS),
                "accessory": PACK_AUTUMN_ACCESSORY,
            },
        )
    )

    for item in ACCESSORIES:
        entries.append(
            ShopEntry(
                sku=f"acc:{item.id}",
                kind="accessory",
                title=item.name,
                subtitle=item.summary,
                price=ACCESSORY_PRICE,
                payload={"item_id": item.id},
            )
        )
    return entries


def find(sku: str) -> ShopEntry:
    for entry in catalog():
        if entry.sku == sku:
            return entry
    raise ShopError("Такого товара нет в магазине.")


class ShopRepo:
    def __init__(self, db: Database, market: MarketRepo) -> None:
        self.db = db
        self.market = market

    @property
    def pool(self) -> asyncpg.Pool:
        return self.db._p()

    async def balance(self, user_id: int) -> int:
        return await self.market.balance(user_id)

    async def my_accessories(self, user_id: int) -> list[dict[str, Any]]:
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                "select id, item_id, card_id from accessories "
                "where user_id = $1 order by id",
                user_id,
            )
        out = []
        for row in rows:
            item = accessory_item(int(row["item_id"]))
            out.append(
                {
                    "id": int(row["id"]),
                    "item_id": item.id,
                    "name": item.name,
                    "summary": item.summary,
                    "card_id": row["card_id"],
                }
            )
        return out

    async def buy(self, user_id: int, sku: str) -> dict[str, Any]:
        """Покупка. Цена берётся из каталога, а не из запроса."""
        entry = find(sku)
        async with self.pool.acquire() as con:
            async with con.transaction():
                row = await con.fetchrow(
                    """
                    update players set bonus_points = bonus_points - $2
                     where user_id = $1 and bonus_points >= $2
                    returning bonus_points
                    """,
                    user_id,
                    entry.price,
                )
                if row is None:
                    balance = await con.fetchval(
                        "select coalesce(bonus_points, 0) from players where user_id = $1",
                        user_id,
                    )
                    raise ShopError(
                        f"Не хватает очков: нужно {entry.price}, "
                        f"у тебя {int(balance or 0)}."
                    )
                granted = await self._grant(con, user_id, entry)
                await con.execute(
                    "insert into shop_log (user_id, sku, price) values ($1, $2, $3)",
                    user_id,
                    entry.sku,
                    entry.price,
                )
        log.info("Игрок %s купил %s за %s", user_id, entry.sku, entry.price)
        return {
            "entry": entry,
            "balance": int(row["bonus_points"]),
            "granted": granted,
        }

    async def _grant(
        self, con: asyncpg.Connection, user_id: int, entry: ShopEntry
    ) -> list[str]:
        granted: list[str] = []
        if entry.kind == "card":
            card_id = str(entry.payload["card_id"])
            await self._add_card(con, user_id, card_id)
            granted.append(get_card(card_id).display_name)
        elif entry.kind == "pack":
            for card_id in entry.payload["cards"]:
                await self._add_card(con, user_id, str(card_id))
                granted.append(get_card(str(card_id)).display_name)
            item_id = int(entry.payload["accessory"])
            await self._add_accessory(con, user_id, item_id)
            granted.append(accessory_item(item_id).name)
        else:
            item_id = int(entry.payload["item_id"])
            await self._add_accessory(con, user_id, item_id)
            granted.append(accessory_item(item_id).name)
        return granted

    @staticmethod
    async def _add_card(con: asyncpg.Connection, user_id: int, card_id: str) -> None:
        """Кладёт карту в коллекцию БЕЗ начисления очков — за неё уже заплачено."""
        await con.execute(
            """
            insert into collection (user_id, card_id, count) values ($1, $2, 1)
            on conflict (user_id, card_id) do update set count = collection.count + 1
            """,
            user_id,
            card_id,
        )

    @staticmethod
    async def _add_accessory(con: asyncpg.Connection, user_id: int, item_id: int) -> None:
        await con.execute(
            "insert into accessories (user_id, item_id) values ($1, $2)",
            user_id,
            int(item_id),
        )
