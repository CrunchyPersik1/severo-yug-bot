"""Кто где стоит в подземелье: живой мир без WebSocket.

Страница раз в 0.6 секунды присылает свою позицию и получает чужие — так
видно, как другие игроки ходят и дерутся. Координаты доверяем странице, как
и урон в прототипе: экономику это не трогает, испортить можно только свою
картинку.

Метка живёт TTL_SECONDS без обновления и потом не показывается. Строка на
игрока одна (primary key), поэтому таблица не растёт.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import asyncpg

from .db import Database

TTL_SECONDS = 6.0        # дольше этого метку не показываем
MAX_REMOTE = 24          # больше в кадр всё равно не влезет
MAX_COORD = 4000.0       # мир по высоте 11 000, по ширине — экран
ANIMS = ("idle", "run", "attack")


def clamp_coord(value: object, limit: float = MAX_COORD) -> float:
    """Любой мусор — в ноль, иначе в границы мира."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if number != number or number in (float("inf"), float("-inf")):  # NaN/inf
        return 0.0
    return max(0.0, min(limit, number))


def clamp_int(value: object, low: int, high: int) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return low
    return max(low, min(high, number))


def clamp_anim(value: object) -> str:
    text = str(value or "").lower()
    return text if text in ANIMS else "idle"


def clamp_weapon(value: object) -> str:
    text = str(value or "").lower()
    return text if text in ("sword", "bow", "staff") else "sword"


def fresh(last_seen: datetime | None, now: datetime, ttl: float = TTL_SECONDS) -> bool:
    if last_seen is None:
        return False
    return (now - last_seen).total_seconds() <= ttl


def stale_before(now: datetime, ttl: float = TTL_SECONDS) -> datetime:
    return now - timedelta(seconds=ttl)


class DungeonPresenceRepo:
    """Одна таблица, два запроса на такт: обновить себя, отдать чужих."""

    def __init__(self, db: Database) -> None:
        self.db = db

    @property
    def pool(self) -> asyncpg.Pool:
        return self.db._p()

    async def touch(self, user_id: int, payload: dict, now: datetime) -> list[dict]:
        zone = clamp_int(payload.get("zone"), 0, 9)
        x = clamp_coord(payload.get("x"))
        y = clamp_coord(payload.get("y"), 20000.0)
        facing = clamp_int(payload.get("facing"), 0, 3)
        anim = clamp_anim(payload.get("anim"))
        hp = clamp_int(payload.get("hp"), 0, 1_000_000)
        max_hp = clamp_int(payload.get("max_hp"), 0, 1_000_000)
        weapon = clamp_weapon(payload.get("weapon"))

        async with self.pool.acquire() as con:
            async with con.transaction():
                await con.execute(
                    """
                    insert into dungeon_presence
                        (user_id, zone, x, y, facing, anim, hp, max_hp, weapon, seen_at)
                    values ($1::bigint, $2::integer, $3::real, $4::real,
                            $5::integer, $6::text, $7::integer, $8::integer,
                            $9::text, $10::timestamptz)
                    on conflict (user_id) do update
                       set zone = excluded.zone,
                           x = excluded.x,
                           y = excluded.y,
                           facing = excluded.facing,
                           anim = excluded.anim,
                           hp = excluded.hp,
                           max_hp = excluded.max_hp,
                           weapon = excluded.weapon,
                           seen_at = excluded.seen_at
                    """,
                    int(user_id),
                    zone,
                    x,
                    y,
                    facing,
                    anim,
                    hp,
                    max_hp,
                    weapon,
                    now,
                )
                rows = await con.fetch(
                    """
                    select p.user_id, p.zone, p.x, p.y, p.facing, p.anim,
                           p.hp, p.max_hp, p.weapon, p.seen_at,
                           coalesce(nullif(pl.first_name, ''), pl.username,
                                    'Игрок') as name
                      from dungeon_presence p
                      left join players pl on pl.user_id = p.user_id
                     where p.user_id <> $1::bigint
                       and p.seen_at > $2::timestamptz
                       and p.zone between $3::integer - 1 and $3::integer + 1
                     order by p.seen_at desc
                     limit $4::integer
                    """,
                    int(user_id),
                    stale_before(now),
                    zone,
                    MAX_REMOTE,
                )
        return [
            {
                "id": int(row["user_id"]),
                "name": str(row["name"]),
                "zone": int(row["zone"]),
                "x": float(row["x"]),
                "y": float(row["y"]),
                "facing": int(row["facing"]),
                "anim": str(row["anim"]),
                "hp": int(row["hp"]),
                "max_hp": int(row["max_hp"]),
                "weapon": str(row["weapon"] or "sword"),
            }
            for row in rows
        ]

    async def drop(self, user_id: int) -> None:
        """Убрать себя с карты (например, при выходе из подземелья)."""
        async with self.pool.acquire() as con:
            await con.execute(
                "delete from dungeon_presence where user_id = $1::bigint", int(user_id)
            )
