"""Прогресс героя подземелья: уровень, монеты, сумка, оружие.

Страница раньше жила только в памяти вкладки: перезагрузил — и герой снова
первого уровня. Теперь прогресс лежит в dungeon_hero, одна строка на игрока.

Данные приходят с клиента (прототип), поэтому всё режем: уровни, монеты,
идентификаторы оружия и размер сумки проверяются здесь, а не «на честном
слове».
"""

from __future__ import annotations

import json
import re

import asyncpg

from .db import Database
from .dungeon_repo import DungeonError

MAX_LEVEL = 999
MAX_EXP = 1_000_000
MAX_COINS = 10 ** 12
MAX_KILLS = 1_000_000
MAX_BAG = 150          # ровно столько оружий генерирует страница: 3 вида × 10 × 5
MAX_TIER = 9           # тиры 0..9, выше улучшать некуда
WEAPON_ID = re.compile(r"^(sword|bow|staff)_([0-9])_([0-4])$")

UPGRADE_BASE = 200     # цена первого улучшения, дальше растёт квадратично

EMPTY = {
    "level": 1,
    "exp": 0,
    "coins": 0,
    "kills": 0,
    "weapon": None,
    "bag": [],
}


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
    if row is None:
        payload = dict(EMPTY)
        payload["upgrade"] = None
        return payload
    payload = {
        "level": int(row["level"]),
        "exp": int(row["exp"]),
        "coins": int(row["coins"]),
        "kills": int(row["kills"]),
        "weapon": row["weapon"],
        "bag": clean_bag(row["bag"]),
    }
    payload["upgrade"] = upgrade_offer(payload["weapon"])
    return payload


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
