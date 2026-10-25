"""Прогресс героя подземелья: уровень, монеты, сумка, оружие, броня.

Страница раньше жила только в памяти вкладки: перезагрузил — и герой снова
первого уровня. Теперь прогресс лежит в dungeon_hero, одна строка на игрока.

Данные приходят с клиента (прототип), поэтому всё режем: уровни, монеты,
идентификаторы оружия и размер сумки проверяются здесь, а не «на честном
слове». Правила брони живут в dungeon.py — их читает и бой, чтобы урон
босса считался в одном месте.
"""

from __future__ import annotations

import json
import re

import asyncpg

from .db import Database
from .dungeon import (
    ARMOR_MAX,
    armor_discount,
    armor_offer,
    armor_price,
)
from .dungeon_repo import DungeonError

MAX_LEVEL = 999
MAX_EXP = 1_000_000
MAX_COINS = 10 ** 12
MAX_KILLS = 1_000_000
MAX_BAG = 150          # ровно столько оружий генерирует страница: 3 вида × 10 × 5
MAX_TIER = 9           # тиры 0..9, выше улучшать некуда
WEAPON_ID = re.compile(r"^(sword|bow|staff)_([0-9])_([0-4])$")

UPGRADE_BASE = 200     # цена первого улучшения, дальше растёт квадратично

EMPTY: dict = {
    "level": 1,
    "exp": 0,
    "coins": 0,
    "kills": 0,
    "weapon": None,
    "bag": [],
    "armor": 0,
}


# --------------------------------------------------------------------------- #
# Санитайзеры
# --------------------------------------------------------------------------- #


def clamp_int(value: object, low: int, high: int, default: int | None = None) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return low if default is None else default
    return max(low, min(high, number))


def clean_weapon(value: object) -> str | None:
    text = str(value or "").strip()
    return text if WEAPON_ID.match(text) else None


def clean_bag(value: object) -> list[str]:
    """Оставляет только валидные id оружия, без повторов, не больше MAX_BAG."""
    if isinstance(value, str):
        try:
            value = json.loads(value)  # из jsonb asyncpg приходит строкой
        except ValueError:
            return []
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if not WEAPON_ID.match(text) or text in result:
            continue
        result.append(text)
        if len(result) >= MAX_BAG:
            break
    return result


# --------------------------------------------------------------------------- #
# Улучшение оружия
# --------------------------------------------------------------------------- #


def parse_weapon(weapon_id: object) -> tuple[str, int, int] | None:
    """'bow_3_1' → ('bow', 3, 1). Мусор → None."""
    match = WEAPON_ID.match(str(weapon_id or "").strip())
    if not match:
        return None
    return match.group(1), int(match.group(2)), int(match.group(3))


def upgrade_price(weapon_id: object) -> int | None:
    """Сколько стоит поднять тир. None — если улучшать уже нечего."""
    parsed = parse_weapon(weapon_id)
    if parsed is None:
        return None
    _, tier, _ = parsed
    if tier >= MAX_TIER:
        return None
    return UPGRADE_BASE * (tier + 1) ** 2


def upgraded_id(weapon_id: object) -> str | None:
    """Тот же вид и вариант, но тиром выше."""
    parsed = parse_weapon(weapon_id)
    if parsed is None:
        return None
    kind, tier, variant = parsed
    if tier >= MAX_TIER:
        return None
    return "%s_%d_%d" % (kind, tier + 1, variant)


def upgrade_offer(weapon_id: object) -> dict | None:
    """Что предложить кнопкой улучшения для оружия в руках."""
    price = upgrade_price(weapon_id)
    target = upgraded_id(weapon_id)
    if price is None or target is None:
        return None
    return {"price": price, "next": target}


def sanitize(payload: dict) -> dict:
    """Приводит присланное клиентом к безопасному виду."""
    bag = clean_bag(payload.get("bag"))
    weapon = clean_weapon(payload.get("weapon"))
    if weapon is None and bag:
        weapon = bag[0]
    if weapon is not None and weapon not in bag:
        bag.insert(0, weapon)
    return {
        "level": clamp_int(payload.get("level"), 1, MAX_LEVEL, 1),
        "exp": clamp_int(payload.get("exp"), 0, MAX_EXP, 0),
        "coins": clamp_int(payload.get("coins"), 0, MAX_COINS, 0),
        "kills": clamp_int(payload.get("kills"), 0, MAX_KILLS, 0),
        "weapon": weapon,
        "bag": bag,
    }


def hero_payload(row: asyncpg.Record | None) -> dict:
    """Готовый к отправке прогресс: всё, что нужно странице."""
    if row is None:
        payload = dict(EMPTY)
        payload["upgrade"] = None
        payload["armor_discount"] = 0.0
        payload["armor_offer"] = armor_offer(0)
        return payload
    armor = int(row["armor"]) if "armor" in row else 0
    payload = {
        "level": int(row["level"]),
        "exp": int(row["exp"]),
        "coins": int(row["coins"]),
        "kills": int(row["kills"]),
        "weapon": row["weapon"],
        "bag": clean_bag(row["bag"]),
        "armor": armor,
        "zone": int(row["zone"]) if "zone" in row and row["zone"] is not None else None,
        "x": float(row["x"]) if "x" in row and row["x"] is not None else None,
        "y": float(row["y"]) if "y" in row and row["y"] is not None else None,
    }
    payload["upgrade"] = upgrade_offer(payload["weapon"])
    payload["armor_discount"] = armor_discount(armor)
    payload["armor_offer"] = armor_offer(armor)
    return payload


# --------------------------------------------------------------------------- #
# База
# --------------------------------------------------------------------------- #


class DungeonHeroRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    @property
    def pool(self) -> asyncpg.Pool:
        return self.db._p()

    async def load(self, user_id: int) -> dict:
        async with self.pool.acquire() as con:
            row = await con.fetchrow(
                "select * from dungeon_hero where user_id = $1::bigint", int(user_id)
            )
        return hero_payload(row)

    async def save(self, user_id: int, payload: dict) -> dict:
        data = sanitize(payload)
        async with self.pool.acquire() as con:
            row = await con.fetchrow(
                """
                insert into dungeon_hero
                    (user_id, level, exp, coins, kills, weapon, bag, updated_at)
                values ($1::bigint, $2::integer, $3::integer, $4::bigint,
                        $5::integer, $6::text, $7::jsonb, now())
                on conflict (user_id) do update
                   set level = excluded.level,
                       exp = excluded.exp,
                       coins = excluded.coins,
                       kills = excluded.kills,
                       weapon = excluded.weapon,
                       bag = excluded.bag,
                       updated_at = now()
                returning *
                """,
                int(user_id),
                data["level"],
                data["exp"],
                data["coins"],
                data["kills"],
                data["weapon"],
                json.dumps(data["bag"]),
            )
        return hero_payload(row)

    async def upgrade(self, user_id: int, weapon_id: object) -> dict:
        """Поднять тир оружия за монеты. Списываем из сохранённого прогресса."""
        source = str(weapon_id or "").strip()
        price = upgrade_price(source)
        target = upgraded_id(source)
        if price is None or target is None:
            raise DungeonError("Дальше улучшать некуда")
        async with self.pool.acquire() as con:
            async with con.transaction():
                row = await con.fetchrow(
                    "select * from dungeon_hero where user_id = $1::bigint for update",
                    int(user_id),
                )
                if row is None:
                    raise DungeonError("Сначала зайди в подземелье")
                bag = clean_bag(row["bag"])
                if source not in bag:
                    raise DungeonError("Этого оружия нет в сумке")
                if int(row["coins"]) < price:
                    raise DungeonError(
                        "Не хватает монет: нужно %d, есть %d" % (price, int(row["coins"]))
                    )
                new_bag = [target if item == source else item for item in bag]
                weapon = target if row["weapon"] == source else row["weapon"]
                row = await con.fetchrow(
                    """
                    update dungeon_hero
                       set coins = coins - $2::bigint,
                           bag = $3::jsonb,
                           weapon = $4::text,
                           updated_at = now()
                     where user_id = $1::bigint
                    returning *
                    """,
                    int(user_id),
                    price,
                    json.dumps(new_bag),
                    weapon,
                )
        return hero_payload(row)

    async def buy_armor(self, user_id: int) -> dict:
        """Поднять броню за Юги кликера. Цена зависит от перерождений."""
        async with self.pool.acquire() as con:
            async with con.transaction():
                row = await con.fetchrow(
                    "select * from dungeon_hero where user_id = $1::bigint for update",
                    int(user_id),
                )
                if row is None:
                    raise DungeonError("Сначала зайди в подземелье")
                resets = int(
                    await con.fetchval(
                        "select coalesce(yugi_resets, 0) from players "
                        "where user_id = $1::bigint",
                        int(user_id),
                    )
                    or 0
                )
                price = armor_price(row["armor"], resets)
                if price is None:
                    raise DungeonError("Броня уже максимальная")
                balance = float(
                    await con.fetchval(
                        "select coalesce(balance, 0) from yugi where user_id = $1::bigint",
                        int(user_id),
                    )
                    or 0
                )
                if balance < price:
                    raise DungeonError(
                        "Не хватает Югов: нужно %d, есть %d" % (price, int(balance))
                    )
                await con.execute(
                    "update yugi set balance = balance - $2::numeric, updated_at = now() "
                    "where user_id = $1::bigint",
                    int(user_id),
                    price,
                )
                row = await con.fetchrow(
                    "update dungeon_hero set armor = armor + 1, updated_at = now() "
                    "where user_id = $1::bigint returning *",
                    int(user_id),
                )
        return hero_payload(row)

    async def top(self, limit: int = 10) -> list[dict]:
        """Таблица лидеров подземелья: уровень, убийства, монеты."""
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                """
                select h.user_id, h.level, h.kills, h.coins, h.armor,
                       coalesce(nullif(p.first_name, ''), p.username, 'Игрок') as name
                  from dungeon_hero h
                  left join players p on p.user_id = h.user_id
                 where h.level > 1 or h.kills > 0 or h.coins > 0
                 order by h.level desc, h.kills desc, h.coins desc
                 limit $1::integer
                """,
                max(1, min(50, int(limit))),
            )
        return [
            {
                "id": int(row["user_id"]),
                "name": str(row["name"])[:32],
                "level": int(row["level"]),
                "kills": int(row["kills"]),
                "coins": int(row["coins"]),
                "armor": int(row["armor"]) if "armor" in row else 0,
            }
            for row in rows
        ]


    async def save_spot(
        self, user_id: int, zone: object, x: object, y: object
    ) -> None:
        """Запомнить, где стоит герой: отсюда показываем его оффлайн."""
        async with self.pool.acquire() as con:
            await con.execute(
                """
                update dungeon_hero
                   set zone = $2::integer, x = $3::real, y = $4::real,
                       seen_at = now(), updated_at = now()
                 where user_id = $1::bigint
                """,
                int(user_id),
                clamp_int(zone, 0, 9),
                max(0.0, min(20000.0, float(x or 0))),
                max(0.0, min(20000.0, float(y or 0))),
            )

    async def offline(self, limit: int = 24) -> list[dict]:
        """Кто играл и вышел: показываем аватаром в углу его локации."""
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                """
                select h.user_id, h.level, h.zone, h.x, h.y, h.weapon, h.armor,
                       h.seen_at,
                       coalesce(nullif(p.first_name, ''), p.username, 'Игрок') as name
                  from dungeon_hero h
                  left join players p on p.user_id = h.user_id
                 where h.zone is not null
                   and h.seen_at is not null
                   and h.seen_at < now() - interval '12 seconds'
                 order by h.seen_at desc
                 limit $1::integer
                """,
                max(1, min(60, int(limit))),
            )
        return [
            {
                "id": int(row["user_id"]),
                "name": str(row["name"])[:24],
                "level": int(row["level"]),
                "zone": int(row["zone"]),
                "x": float(row["x"] or 0),
                "y": float(row["y"] or 0),
                "weapon": str(row["weapon"] or "sword"),
                "armor": int(row["armor"]) if "armor" in row else 0,
            }
            for row in rows
        ]
