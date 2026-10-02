"""Слой доступа к PostgreSQL (Supabase) на asyncpg.

Ничего не хранится в памяти и на диске Render: всё состояние боёв — в таблице battles.
"""

from __future__ import annotations

import json
import logging
import ssl as ssl_module
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg

log = logging.getLogger(__name__)

_STRIP_PARAMS = {"sslmode", "pgbouncer", "connection_limit", "ssl", "application_name"}


def prepare_dsn(database_url: str) -> tuple[str, Any, int]:
    """Чистит DSN от параметров, которые не понимает asyncpg.

    Возвращает (dsn, ssl_arg, statement_cache_size).
    Supabase-пулер не поддерживает prepared statements -> кеш отключаем.
    """
    parts = urlsplit(database_url)
    host = (parts.hostname or "").lower()
    port = parts.port

    sslmode = ""
    kept: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() == "sslmode":
            sslmode = value.lower()
            continue
        if key.lower() in _STRIP_PARAMS:
            continue
        kept.append((key, value))

    dsn = urlunsplit(parts._replace(query=urlencode(kept)))

    is_local = host in {"localhost", "127.0.0.1", "::1", "postgres"}
    pooler = "pooler.supabase" in host or port == 6543

    if sslmode in {"disable", "allow"} or is_local:
        ssl_arg: Any = False
    elif sslmode in {"verify-ca", "verify-full"}:
        ssl_arg = ssl_module.create_default_context()
    else:
        context = ssl_module.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl_module.CERT_NONE
        ssl_arg = context

    return dsn, ssl_arg, 0 if pooler else 100


class Database:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self.pool: asyncpg.Pool | None = None

    # ------------------------------------------------------------------ #
    # Жизненный цикл
    # ------------------------------------------------------------------ #

    async def connect(self) -> None:
        dsn, ssl_arg, statement_cache = prepare_dsn(self._dsn)
        self.pool = await asyncpg.create_pool(
            dsn,
            ssl=ssl_arg,
            min_size=1,
            max_size=5,
            max_inactive_connection_lifetime=120,
            command_timeout=30,
            statement_cache_size=statement_cache,
        )
        log.info("Postgres pool создан (ssl=%s, cache=%s)", bool(ssl_arg), statement_cache)

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    def _p(self) -> asyncpg.Pool:
        if self.pool is None:
            raise RuntimeError("Пул БД не создан")
        return self.pool

    async def ping(self) -> bool:
        """Дешёвая проверка живости БД. Заодно не даёт Supabase уснуть."""
        async with self._p().acquire() as con:
            return bool(await con.fetchval("select 1"))

    async def init_schema(self) -> None:
        """Применяет schema.sql (idempotent)."""
        import pathlib

        sql_path = pathlib.Path(__file__).resolve().parent.parent / "schema.sql"
        sql = sql_path.read_text(encoding="utf-8")
        async with self._p().acquire() as con:
            await con.execute(sql)
        log.info("Схема БД актуальна")

    async def upsert_cards(self, cards: list[dict[str, Any]]) -> None:
        async with self._p().acquire() as con:
            await con.executemany(
                """
                insert into cards (card_id, name, rarity, points, hp, atk,
                                   ability_name, ability_cd, ability)
                values ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
                on conflict (card_id) do update set
                    name = excluded.name,
                    rarity = excluded.rarity,
                    points = excluded.points,
                    hp = excluded.hp,
                    atk = excluded.atk,
                    ability_name = excluded.ability_name,
                    ability_cd = excluded.ability_cd,
                    ability = excluded.ability
                """,
                cards,
            )

    # ------------------------------------------------------------------ #
    # Игроки и коллекция
    # ------------------------------------------------------------------ #

    async def ensure_player(self, user_id: int, username: str | None, first_name: str | None) -> None:
        async with self._p().acquire() as con:
            await con.execute(
                """
                insert into players (user_id, username, first_name)
                values ($1, $2, $3)
                on conflict (user_id) do update set
                    username = excluded.username,
                    first_name = excluded.first_name,
                    updated_at = now()
                """,
                user_id,
                username,
                first_name,
            )

    async def claim_daily(self, user_id: int, day: Any) -> bool:
        """Атомарно забирает суточный лимит. True — выпадание разрешено."""
        async with self._p().acquire() as con:
            row = await con.fetchrow(
                """
                update players
                   set last_drop_day = $2, updated_at = now()
                 where user_id = $1
                   and (last_drop_day is null or last_drop_day < $2)
                returning user_id
                """,
                user_id,
                day,
            )
            return row is not None

    async def add_card(self, user_id: int, card_id: str) -> int:
        async with self._p().acquire() as con:
            row = await con.fetchrow(
                """
                insert into collection (user_id, card_id, count)
                values ($1, $2, 1)
                on conflict (user_id, card_id) do update set count = collection.count + 1
                returning count
                """,
                user_id,
                card_id,
            )
            return int(row["count"])

    async def add_drop(self, user_id: int, chat_id: int | None, card_id: str, day: Any) -> None:
        async with self._p().acquire() as con:
            await con.execute(
                "insert into drops (user_id, chat_id, card_id, day_key) values ($1, $2, $3, $4)",
                user_id,
                chat_id,
                card_id,
                day,
            )

    async def get_collection(self, user_id: int) -> dict[str, int]:
        async with self._p().acquire() as con:
            rows = await con.fetch(
                "select card_id, count from collection where user_id = $1", user_id
            )
        return {row["card_id"]: int(row["count"]) for row in rows}

    async def collection_points(self, user_id: int) -> int:
        async with self._p().acquire() as con:
            row = await con.fetchrow(
                """
                select coalesce(sum(c.points), 0) as points, count(*) as unique_cards,
                       coalesce(sum(col.count), 0) as total_cards
                  from collection col
                  join cards c on c.card_id = col.card_id
                 where col.user_id = $1
                """,
                user_id,
            )
        return int(row["points"])

    async def collection_stats(self, user_id: int) -> dict[str, int]:
        async with self._p().acquire() as con:
            row = await con.fetchrow(
                """
                select coalesce(sum(c.points), 0) as points,
                       count(*) as unique_cards,
                       coalesce(sum(col.count), 0) as total_cards
                  from collection col
                  join cards c on c.card_id = col.card_id
                 where col.user_id = $1
                """,
                user_id,
            )
        return {
            "points": int(row["points"]),
            "unique_cards": int(row["unique_cards"]),
            "total_cards": int(row["total_cards"]),
        }

    async def top_players(self, limit: int = 10) -> list[dict[str, Any]]:
        async with self._p().acquire() as con:
            rows = await con.fetch(
                """
                select p.user_id, p.username, p.first_name,
                       coalesce(sum(c.points), 0) as points,
                       count(col.card_id) as unique_cards
                  from players p
                  left join collection col on col.user_id = p.user_id
                  left join cards c on c.card_id = col.card_id
                 group by p.user_id, p.username, p.first_name
                having count(col.card_id) > 0
                 order by points desc, unique_cards desc
                 limit $1
                """,
                limit,
            )
        return [dict(row) for row in rows]

    async def record_result(self, winner_id: int | None, loser_id: int | None, draw: bool = False) -> None:
        async with self._p().acquire() as con:
            if draw:
                await con.execute(
                    "update players set draws = draws + 1 where user_id = any($1::bigint[])",
                    [winner_id, loser_id],
                )
            else:
                if winner_id is not None:
                    await con.execute(
                        "update players set wins = wins + 1 where user_id = $1", winner_id
                    )
                if loser_id is not None:
                    await con.execute(
                        "update players set losses = losses + 1 where user_id = $1", loser_id
                    )

    # ------------------------------------------------------------------ #
    # Бои
    # ------------------------------------------------------------------ #

    async def create_battle(self, battle_id: str, chat_id: int, challenger_id: int, opponent_id: int, state: dict[str, Any]) -> None:
        async with self._p().acquire() as con:
            await con.execute(
                """
                insert into battles (battle_id, chat_id, challenger_id, opponent_id, state, status)
                values ($1, $2, $3, $4, $5::jsonb, 'choosing')
                """,
                battle_id,
                chat_id,
                challenger_id,
                opponent_id,
                json.dumps(state),
            )

    async def get_battle(self, battle_id: str) -> dict[str, Any] | None:
        async with self._p().acquire() as con:
            row = await con.fetchrow("select * from battles where battle_id = $1", battle_id)
        return self._row_to_battle(row)

    async def mutate_battle(
        self,
        battle_id: str,
        mutator: Callable[[dict[str, Any], dict[str, Any]], tuple[Any, dict[str, Any] | None]],
    ) -> tuple[dict[str, Any] | None, Any]:
        """Транзакционно меняет бой. mutator(row, state) -> (result, extra_columns)."""
        async with self._p().acquire() as con:
            async with con.transaction():
                row = await con.fetchrow(
                    "select * from battles where battle_id = $1 for update", battle_id
                )
                if row is None:
                    return None, None
                battle = self._row_to_battle(row)
                assert battle is not None
                state = battle["state"]
                result, extra = mutator(battle, state)
                extra = extra or {}
                await con.execute(
                    """
                    update battles
                       set state = $2::jsonb,
                           status = $3,
                           winner_id = $4,
                           turn_no = $5,
                           message_id = coalesce($6, message_id),
                           chat_id = coalesce($7, chat_id),
                           pick_a_chat = coalesce($8, pick_a_chat),
                           pick_a_msg = coalesce($9, pick_a_msg),
                           pick_b_chat = coalesce($10, pick_b_chat),
                           pick_b_msg = coalesce($11, pick_b_msg),
                           version = version + 1,
                           updated_at = now()
                     where battle_id = $1
                    """,
                    battle_id,
                    json.dumps(state),
                    extra.get("status", battle["status"]),
                    extra.get("winner_id", battle["winner_id"]),
                    extra.get("turn_no", state.get("turn_no", battle["turn_no"])),
                    extra.get("message_id"),
                    extra.get("chat_id"),
                    extra.get("pick_a_chat"),
                    extra.get("pick_a_msg"),
                    extra.get("pick_b_chat"),
                    extra.get("pick_b_msg"),
                )
                battle.update(extra)
                battle["state"] = state
                battle["version"] = int(battle.get("version") or 0) + 1
                return battle, result

    async def stale_battles(self, choosing_seconds: int, active_seconds: int) -> list[dict[str, Any]]:
        async with self._p().acquire() as con:
            rows = await con.fetch(
                """
                select * from battles
                 where (status = 'choosing' and updated_at < now() - make_interval(secs => $1))
                    or (status = 'active'   and updated_at < now() - make_interval(secs => $2))
                 order by updated_at
                 limit 50
                """,
                float(choosing_seconds),
                float(active_seconds),
            )
        return [b for b in (self._row_to_battle(row) for row in rows) if b is not None]

    async def user_active_battles(self, user_id: int) -> int:
        async with self._p().acquire() as con:
            row = await con.fetchrow(
                """
                select count(*) as n from battles
                 where status in ('choosing', 'active')
                   and (challenger_id = $1 or opponent_id = $1)
                """,
                user_id,
            )
        return int(row["n"])

    @staticmethod
    def _row_to_battle(row: asyncpg.Record | None) -> dict[str, Any] | None:
        if row is None:
            return None
        battle = dict(row)
        state = battle.get("state")
        if isinstance(state, str):
            battle["state"] = json.loads(state)
        return battle
