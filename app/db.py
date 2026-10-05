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
                                   ability_name, ability_cd, ability, surname)
                values ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10)
                on conflict (card_id) do update set
                    name = excluded.name,
                    rarity = excluded.rarity,
                    points = excluded.points,
                    hp = excluded.hp,
                    atk = excluded.atk,
                    ability_name = excluded.ability_name,
                    ability_cd = excluded.ability_cd,
                    ability = excluded.ability,
                    surname = excluded.surname
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

    async def claim_roulette(self, user_id: int, day: Any) -> bool:
        """Атомарно забирает суточный спин рулетки (сброс в 15:00 UTC)."""
        async with self._p().acquire() as con:
            row = await con.fetchrow(
                """
                update players
                   set roulette_day = $2, updated_at = now()
                 where user_id = $1
                   and (roulette_day is null or roulette_day < $2)
                returning user_id
                """,
                user_id,
                day,
            )
        return row is not None

    async def add_points(self, user_id: int, amount: int) -> int:
        async with self._p().acquire() as con:
            row = await con.fetchrow(
                """
                update players set bonus_points = bonus_points + $2
                 where user_id = $1
                returning bonus_points
                """,
                user_id,
                int(amount),
            )
        return int(row["bonus_points"]) if row else 0

    async def add_case(self, user_id: int, source: str = "roulette") -> int:
        async with self._p().acquire() as con:
            value = await con.fetchval(
                "insert into cases (user_id, source) values ($1, $2) returning id",
                user_id,
                source,
            )
        return int(value)

    async def user_cases(
        self,
        user_id: int,
        include_listed: bool = False,
        include_opened: bool = False,
    ) -> list[dict[str, Any]]:
        """По умолчанию — только закрытые кейсы, которые не на рынке.

        Открытый кейс остаётся в таблице как история, но игроку не показывается
        и повторно открыть его нельзя.
        """
        query = "select id, opened, listed, source, created_at from cases where user_id = $1"
        if not include_listed:
            query += " and listed = false"
        if not include_opened:
            query += " and opened = false"
        query += " order by id"
        async with self._p().acquire() as con:
            rows = await con.fetch(query, user_id)
        return [dict(row) for row in rows]

    async def open_case(self, user_id: int, case_id: int) -> bool:
        """Помечает кейс открытым. False — кейса нет, он открыт или выставлен на продажу."""
        async with self._p().acquire() as con:
            row = await con.fetchrow(
                """
                update cases set opened = true
                 where id = $1 and user_id = $2 and opened = false and listed = false
                returning id
                """,
                int(case_id),
                user_id,
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

    async def get_card_kills(self, user_id: int) -> dict[str, int]:
        async with self._p().acquire() as con:
            rows = await con.fetch(
                "select card_id, kills from collection where user_id = $1", user_id
            )
        return {row["card_id"]: int(row["kills"]) for row in rows}

    async def collection_stats(self, user_id: int) -> dict[str, int]:
        async with self._p().acquire() as con:
            row = await con.fetchrow(
                """
                select coalesce(sum(c.points), 0) as points,
                       count(col.card_id) as unique_cards,
                       coalesce(sum(col.count), 0) as total_cards,
                       coalesce(sum(col.kills), 0) as card_kills
                  from collection col
                  join cards c on c.card_id = col.card_id
                 where col.user_id = $1
                """,
                user_id,
            )
            bonus = await con.fetchval(
                "select coalesce(bonus_points, 0) from players where user_id = $1", user_id
            )
        bonus = int(bonus or 0)
        points = int(row["points"])
        # Очки — единая валюта: баланс и есть счёт игрока, а points — справочная
        # стоимость коллекции (за неё очки уже начислены при выпадении).
        return {
            "points": points,
            "bonus": bonus,
            "total": max(0, bonus),
            "unique_cards": int(row["unique_cards"]),
            "total_cards": int(row["total_cards"]),
            "card_kills": int(row["card_kills"]),
        }

    async def player_profile(self, user_id: int) -> dict[str, Any] | None:
        """Полный профиль игрока + место в PvP-рейтинге."""
        async with self._p().acquire() as con:
            row = await con.fetchrow(
                """
                select p.user_id, p.username, p.first_name,
                       p.wins, p.losses, p.draws, p.kills, p.bonus_points,
                       coalesce(sum(c.points), 0) as card_points,
                       count(col.card_id) as unique_cards,
                       coalesce(sum(col.count), 0) as total_cards,
                       coalesce(sum(col.kills), 0) as card_kills
                  from players p
                  left join collection col on col.user_id = p.user_id
                  left join cards c on c.card_id = col.card_id
                 where p.user_id = $1
                 group by p.user_id
                """,
                user_id,
            )
            if row is None:
                return None
            rank = await con.fetchval(
                "select count(*) + 1 from players where wins > $1", int(row["wins"])
            )
        profile = dict(row)
        profile["rank"] = int(rank or 1)
        profile["total"] = max(0, int(profile["bonus_points"]))
        return profile

    async def rating(self, limit: int = 10) -> list[dict[str, Any]]:
        """Рейтинг PvP по числу выигранных боёв."""
        async with self._p().acquire() as con:
            rows = await con.fetch(
                """
                select user_id, username, first_name, wins, losses, draws, kills
                  from players
                 where wins + losses + draws > 0
                 order by wins desc, kills desc, losses asc
                 limit $1
                """,
                limit,
            )
        return [dict(row) for row in rows]

    async def top_players(self, limit: int = 10) -> list[dict[str, Any]]:
        async with self._p().acquire() as con:
            rows = await con.fetch(
                """
                select p.user_id, p.username, p.first_name, p.wins, p.kills,
                       greatest(p.bonus_points, 0) as points,
                       coalesce(sum(c.points), 0) as card_points,
                       p.bonus_points,
                       count(col.card_id) as unique_cards
                  from players p
                  left join collection col on col.user_id = p.user_id
                  left join cards c on c.card_id = col.card_id
                 group by p.user_id, p.username, p.first_name, p.bonus_points,
                          p.wins, p.kills
                having greatest(p.bonus_points, 0) > 0 or count(col.card_id) > 0
                 order by points desc, unique_cards desc
                 limit $1
                """,
                limit,
            )
        return [dict(row) for row in rows]

    async def apply_battle_result(
        self,
        winner_id: int,
        loser_id: int,
        draw: bool = False,
        winner_card_id: str | None = None,
        loser_card_id: str | None = None,
        stake: int = 0,
    ) -> None:
        """Итог боя одной транзакцией: победы/поражения, убийства и передача очков."""
        async with self._p().acquire() as con:
            async with con.transaction():
                if draw:
                    await con.execute(
                        "update players set draws = draws + 1 where user_id = any($1::bigint[])",
                        [winner_id, loser_id],
                    )
                    return
                await con.execute(
                    """
                    update players
                       set wins = wins + 1,
                           kills = kills + 1,
                           bonus_points = bonus_points + $2
                     where user_id = $1
                    """,
                    winner_id,
                    int(stake),
                )
                await con.execute(
                    """
                    update players
                       set losses = losses + 1,
                           bonus_points = bonus_points - $2
                     where user_id = $1
                    """,
                    loser_id,
                    int(stake),
                )
                if winner_card_id:
                    await con.execute(
                        "update collection set kills = kills + 1 where user_id = $1 and card_id = $2",
                        winner_id,
                        winner_card_id,
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
