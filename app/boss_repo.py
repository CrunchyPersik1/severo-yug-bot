"""Рейд-босс: состояние рейда, удары и вклад игроков. Всё в транзакциях.

Все параметры в SQL идут с явными кастами: без них Postgres ругался
«could not determine data type of parameter» (на этом уже один раз
зависла биржа).
"""

from __future__ import annotations

from datetime import datetime

import asyncpg

from . import boss
from .db import Database


class BossError(Exception):
    """Ошибку можно показать игроку."""


class BossRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    @property
    def pool(self) -> asyncpg.Pool:
        return self.db._p()

    async def start(
        self, name: str, hp: int, chat_id: int | None = None
    ) -> dict:
        """Запускает рейд: прошлые активные закрывает."""
        hp = max(1, int(hp))
        async with self.pool.acquire() as con:
            async with con.transaction():
                await con.execute(
                    "update boss_raid set status = 'dead', "
                    "killed_at = coalesce(killed_at, now()) where status = 'active'"
                )
                row = await con.fetchrow(
                    """
                    insert into boss_raid (name, hp, max_hp, hit_damage, chat_id)
                    values ($1::text, $2::bigint, $2::bigint, $3::integer,
                            $4::bigint)
                    returning *
                    """,
                    str(name),
                    hp,
                    int(boss.HIT_DAMAGE),
                    chat_id,
                )
        return dict(row)

    async def get(self, boss_id: int) -> dict | None:
        async with self.pool.acquire() as con:
            row = await con.fetchrow(
                "select * from boss_raid where id = $1::bigint", int(boss_id)
            )
        return dict(row) if row else None

    async def active(self) -> dict | None:
        async with self.pool.acquire() as con:
            row = await con.fetchrow(
                "select * from boss_raid where status = 'active' "
                "order by id desc limit 1"
            )
        return dict(row) if row else None

    async def attach(self, boss_id: int, chat_id: int, message_id: int) -> None:
        async with self.pool.acquire() as con:
            await con.execute(
                "update boss_raid set chat_id = $2::bigint, message_id = $3::bigint "
                "where id = $1::bigint",
                int(boss_id),
                int(chat_id),
                int(message_id),
            )

    async def my_hits(self, boss_id: int, user_id: int) -> dict:
        async with self.pool.acquire() as con:
            row = await con.fetchrow(
                "select hits, damage from boss_hits "
                "where boss_id = $1::bigint and user_id = $2::bigint",
                int(boss_id),
                int(user_id),
            )
        if row is None:
            return {"hits": 0, "damage": 0}
        return {"hits": int(row["hits"]), "damage": int(row["damage"])}

    async def stats(self, boss_id: int) -> dict:
        async with self.pool.acquire() as con:
            row = await con.fetchrow(
                """
                select count(*)::int as people,
                       coalesce(sum(hits), 0)::bigint as hits,
                       coalesce(sum(damage), 0)::bigint as damage
                  from boss_hits where boss_id = $1::bigint
                """,
                int(boss_id),
            )
        return {
            "people": int(row["people"]),
            "hits": int(row["hits"]),
            "damage": int(row["damage"]),
        }

    async def top(self, boss_id: int, limit: int = 5) -> list[dict]:
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                """
                select h.user_id, h.hits, h.damage,
                       coalesce(nullif(p.first_name, ''), p.username) as name
                  from boss_hits h
                  left join players p on p.user_id = h.user_id
                 where h.boss_id = $1::bigint
                 order by h.damage desc, h.user_id
                 limit $2::integer
                """,
                int(boss_id),
                int(limit),
            )
        return [dict(row) for row in rows]

    async def hit(self, boss_id: int, user_id: int, now: datetime) -> dict:
        """Один удар. Возвращает новый HP и добили ли босса."""
        async with self.pool.acquire() as con:
            async with con.transaction():
                row = await con.fetchrow(
                    "select * from boss_raid where id = $1::bigint for update",
                    int(boss_id),
                )
                if row is None:
                    raise BossError("Такого босса уже нет.")
                if row["status"] != "active":
                    raise BossError("Босс уже повержен — жди следующего рейда.")
                last = await con.fetchrow(
                    "select updated_at from boss_hits "
                    "where boss_id = $1::bigint and user_id = $2::bigint",
                    int(boss_id),
                    int(user_id),
                )
                if last is not None:
                    age = (now - last["updated_at"]).total_seconds()
                    if age < boss.HIT_COOLDOWN_SECONDS:
                        return {
                            "cooldown": True,
                            "left": round(boss.HIT_COOLDOWN_SECONDS - age, 1),
                        }
                damage = int(row["hit_damage"])
                new_hp = max(0, int(row["hp"]) - damage)
                await con.execute(
                    """
                    update boss_raid
                       set hp = $2::bigint,
                           status = case when $2::bigint <= 0 then 'dead'
                                         else status end,
                           killed_at = case when $2::bigint <= 0 then now()
                                            else killed_at end
                     where id = $1::bigint
                    """,
                    int(boss_id),
                    int(new_hp),
                )
                await con.execute(
                    """
                    insert into boss_hits (boss_id, user_id, hits, damage)
                    values ($1::bigint, $2::bigint, 1, $3::bigint)
                    on conflict (boss_id, user_id) do update
                       set hits = boss_hits.hits + 1,
                           damage = boss_hits.damage + $3::bigint,
                           updated_at = now()
                    """,
                    int(boss_id),
                    int(user_id),
                    damage,
                )
        return {
            "cooldown": False,
            "hp": new_hp,
            "max_hp": int(row["max_hp"]),
            "damage": damage,
            "dead": new_hp <= 0,
        }

    async def mark_rewarded(self, boss_id: int) -> bool:
        """True, если именно этот вызов начисляет награду (защита от дублей)."""
        async with self.pool.acquire() as con:
            row = await con.fetchrow(
                "update boss_raid set rewarded_at = now() "
                "where id = $1::bigint and rewarded_at is null returning id",
                int(boss_id),
            )
        return row is not None
