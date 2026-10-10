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

from .items import ACCESSORIES as _ACCESSORIES
from .market import sum_bonus as _sum_bonus

log = logging.getLogger(__name__)

_STRIP_PARAMS = {"sslmode", "pgbouncer", "connection_limit", "ssl", "application_name"}


def as_json_dict(value: Any) -> dict[str, Any]:
    """asyncpg отдаёт jsonb строкой — приводим к словарю безопасно."""
    if not value:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return dict(value) if isinstance(value, dict) else {}


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

    async def purge_missing_cards(self, known_ids: list[str]) -> None:
        """Убирает из базы карты, которых больше нет в коде.

        Раньше удалённая из каталога карта (например, «Стринги») оставалась
        у игроков в collection/inventory, и просмотр профиля падал на get_card().
        """
        if not known_ids:
            return
        async with self._p().acquire() as con:
            async with con.transaction():
                await con.execute(
                    "delete from market where card_id is not null "
                    "and not (card_id = any($1::text[]))",
                    known_ids,
                )
                await con.execute(
                    "delete from inventory where not (card_id = any($1::text[]))",
                    known_ids,
                )
                await con.execute(
                    "delete from collection where not (card_id = any($1::text[]))",
                    known_ids,
                )
                await con.execute(
                    "delete from casino_lost where not (card_id = any($1::text[]))",
                    known_ids,
                )
                removed = await con.execute(
                    "delete from cards where not (card_id = any($1::text[]))",
                    known_ids,
                )
        log.info("Устаревшие карты вычищены: %s", removed)

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
                    -- не затираем сохранённое пустыми значениями: профиль можно
                    -- открыть по @username, где имени под рукой нет
                    username = coalesce(excluded.username, players.username),
                    first_name = coalesce(excluded.first_name, players.first_name),
                    updated_at = now()
                """,
                user_id,
                username,
                first_name,
            )

    async def claim_daily(self, user_id: int, day: Any, limit: int = 1) -> int | None:
        """Атомарно тратит одну попытку. Возвращает остаток или None, если нельзя.

        При смене дня счётчик обнуляется, а лимит возвращается к дефолтному.
        """
        async with self._p().acquire() as con:
            row = await con.fetchrow(
                """
                update players
                   set drop_uses = case when last_drop_day = $2 then drop_uses + 1 else 1 end,
                       drop_limit = case when last_drop_day = $2 then drop_limit else $3 end,
                       last_drop_day = $2,
                       updated_at = now()
                 where user_id = $1
                   and (last_drop_day is distinct from $2 or drop_uses < drop_limit)
                returning drop_limit - drop_uses as left
                """,
                user_id,
                day,
                int(limit),
            )
        return None if row is None else int(row["left"])

    async def grant_drop_limit(
        self, user_id: int, day: Any, amount: int, default_limit: int = 1
    ) -> int:
        """Выдаёт дополнительные попытки «Северо-Юг» на текущие сутки.

        Если день ещё не начинался, сначала выставляем обычный лимит, потом
        добавляем к нему amount. Возвращает, сколько попыток осталось.
        """
        async with self._p().acquire() as con:
            async with con.transaction():
                row = await con.fetchrow(
                    "select last_drop_day, drop_uses, drop_limit "
                    "from players where user_id = $1 for update",
                    user_id,
                )
                if row is None:
                    return int(amount)
                if row["last_drop_day"] != day:
                    uses, limit = 0, int(default_limit)
                else:
                    uses = int(row["drop_uses"])
                    limit = int(row["drop_limit"])
                new_limit = limit + int(amount)
                await con.execute(
                    """
                    update players
                       set last_drop_day = $2,
                           drop_uses = $3,
                           drop_limit = $4,
                           updated_at = now()
                     where user_id = $1
                    """,
                    user_id,
                    day,
                    uses,
                    new_limit,
                )
                return max(0, new_limit - uses)

    async def grant_boss_rewards(
        self,
        drop_day: Any,
        spin_day: Any,
        drops: int,
        spins: int,
        cases: int,
    ) -> int:
        """Награда всем за рейд-босса: крутки, спины и кейсы.

        Возвращает, скольким игрокам выдали.
        """
        async with self._p().acquire() as con:
            async with con.transaction():
                await con.execute(
                    """
                    update players
                       set last_drop_day = $1::date,
                           drop_uses = 0,
                           drop_limit = drop_limit + $3::integer,
                           roulette_day = $2::date,
                           roulette_uses = 0,
                           roulette_limit = roulette_limit + $4::integer,
                           updated_at = now()
                    """,
                    drop_day,
                    spin_day,
                    int(drops),
                    int(spins),
                )
                if int(cases) > 0:
                    await con.execute(
                        """
                        insert into cases (user_id, source)
                        select p.user_id, 'boss' from players p
                        cross join generate_series(1, $1::integer)
                        """,
                        int(cases),
                    )
                total = await con.fetchval("select count(*) from players")
        return int(total or 0)

    async def claim_roulette(self, user_id: int, day: Any, limit: int = 1) -> int | None:
        """Атомарно тратит один спин рулетки. Возвращает остаток или None."""
        async with self._p().acquire() as con:
            row = await con.fetchrow(
                """
                update players
                   set roulette_uses = case when roulette_day = $2 then roulette_uses + 1 else 1 end,
                       roulette_limit = case when roulette_day = $2 then roulette_limit else $3 end,
                       roulette_day = $2,
                       updated_at = now()
                 where user_id = $1
                   and (roulette_day is distinct from $2 or roulette_uses < roulette_limit)
                returning roulette_limit - roulette_uses as left
                """,
                user_id,
                day,
                int(limit),
            )
        return None if row is None else int(row["left"])

    async def roulette_left(self, user_id: int, day: Any, limit: int = 1) -> int:
        """Сколько спинов рулетки осталось на текущие сутки."""
        async with self._p().acquire() as con:
            row = await con.fetchrow(
                "select roulette_day, roulette_uses, roulette_limit "
                "from players where user_id = $1",
                user_id,
            )
        if row is None:
            return 0
        if row["roulette_day"] != day:
            return int(limit)
        return max(0, int(row["roulette_limit"]) - int(row["roulette_uses"]))

    async def grant_spin_limit(
        self, user_id: int, day: Any, amount: int, default_limit: int = 1
    ) -> int:
        """Выдаёт дополнительные спины рулетки на текущие сутки."""
        async with self._p().acquire() as con:
            async with con.transaction():
                row = await con.fetchrow(
                    "select roulette_day, roulette_uses, roulette_limit "
                    "from players where user_id = $1 for update",
                    user_id,
                )
                if row is None:
                    return int(amount)
                if row["roulette_day"] != day:
                    uses, limit = 0, int(default_limit)
                else:
                    uses = int(row["roulette_uses"])
                    limit = int(row["roulette_limit"])
                new_limit = limit + int(amount)
                await con.execute(
                    """
                    update players
                       set roulette_day = $2,
                           roulette_uses = $3,
                           roulette_limit = $4,
                           updated_at = now()
                     where user_id = $1
                    """,
                    user_id,
                    day,
                    uses,
                    new_limit,
                )
                return max(0, new_limit - uses)

    async def get_setting(self, key: str) -> str | None:
        async with self._p().acquire() as con:
            return await con.fetchval(
                "select value from app_settings where key = $1", str(key)
            )

    async def set_setting(self, key: str, value: str) -> None:
        async with self._p().acquire() as con:
            await con.execute(
                "insert into app_settings (key, value) values ($1, $2) "
                "on conflict (key) do update set value = excluded.value",
                str(key),
                str(value),
            )

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
            # улучшенные копии живут в inventory и в прошлую сумму не попадали
            inv_points = await con.fetchval(
                """
                select coalesce(sum(c.points), 0)
                  from inventory i join cards c on c.card_id = i.card_id
                 where i.user_id = $1
                """,
                user_id,
            )
        bonus = int(bonus or 0)
        points = int(row["points"]) + int(inv_points or 0)
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

    async def touch_chat(self, chat_id: int, kind: str, title: str | None = None) -> None:
        """Запоминает чат — из него потом идёт админская рассылка."""
        async with self._p().acquire() as con:
            await con.execute(
                """
                insert into chats (chat_id, kind, title) values ($1, $2, $3)
                on conflict (chat_id) do update
                   set kind = excluded.kind,
                       title = coalesce(excluded.title, chats.title),
                       last_seen = now(),
                       left_at = null
                """,
                chat_id,
                kind,
                title,
            )

    async def mark_chat_left(self, chat_id: int) -> None:
        async with self._p().acquire() as con:
            await con.execute(
                "update chats set left_at = now() where chat_id = $1", chat_id
            )

    async def broadcast_targets(self) -> list[int]:
        """Живые группы и супергруппы. Лички в рассылку не попадают."""
        async with self._p().acquire() as con:
            rows = await con.fetch(
                """
                select chat_id from chats
                 where left_at is null and kind in ('group', 'supergroup')
                 order by last_seen desc
                """
            )
        return [int(row["chat_id"]) for row in rows]

    async def all_player_ids(self) -> list[int]:
        """Все игроки — для личных оповещений (биржа и т.п.)."""
        async with self._p().acquire() as con:
            rows = await con.fetch("select user_id from players")
        return [int(row["user_id"]) for row in rows]

    async def chat_count(self) -> dict[str, int]:
        async with self._p().acquire() as con:
            row = await con.fetchrow(
                """
                select count(*) filter (where left_at is null) as alive,
                       count(*) as total
                  from chats where kind in ('group', 'supergroup')
                """
            )
        return {"alive": int(row["alive"]), "total": int(row["total"])}

    async def player_profile(self, user_id: int) -> dict[str, Any] | None:
        """Полный профиль: статистика, активность и любимая карта."""
        async with self._p().acquire() as con:
            row = await con.fetchrow(
                """
                select p.user_id, p.username, p.first_name,
                       p.wins, p.losses, p.draws, p.kills, p.bonus_points,
                       p.favorite_card,
                       coalesce(sum(c.points), 0) as card_points,
                       count(col.card_id) as unique_cards,
                       coalesce(sum(col.count), 0) as total_cards,
                       coalesce(sum(col.kills), 0) as card_kills,
                       coalesce((select sum(c2.points) from inventory i
                                  join cards c2 on c2.card_id = i.card_id
                                 where i.user_id = p.user_id), 0) as inv_points,
                       (select count(*) from inventory i2
                         where i2.user_id = p.user_id) as upgraded,
                       (select count(*) from drops d
                         where d.user_id = p.user_id) as drops,
                       (select count(*) from casino_log cl
                         where cl.user_id = p.user_id) as casino_bets,
                       (select count(*) from shop_log sl
                         where sl.user_id = p.user_id) as shop_buys,
                       (select count(*) from history h
                         where h.buyer_id = p.user_id or h.seller_id = p.user_id)
                         as market_deals,
                       (select count(*) from gifts g
                         where g.sender_id = p.user_id) as gifts_sent,
                       (select count(*) from referrals r
                         where r.referrer_id = p.user_id) as invited,
                       (select count(*) from promo_uses pu
                         where pu.user_id = p.user_id) as promos
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
            favorite = await con.fetchrow(
                """
                select card_id, sum(kills) as kills, sum(copies) as copies
                  from (
                        select card_id, kills, collection.count::int as copies
                          from collection where user_id = $1
                        union all
                        select card_id, 0 as kills, 1 as copies
                          from inventory where user_id = $1
                       ) t
                 group by card_id
                 order by kills desc, copies desc, card_id
                 limit 1
                """,
                user_id,
            )
            # Ручной выбор важнее автоматического.
            chosen = row["favorite_card"] or (favorite["card_id"] if favorite else None)
            card_stats = None
            if chosen:
                card_stats = await con.fetchrow(
                    """
                    select
                        coalesce((select c0.kills from collection c0
                                   where c0.user_id = $1 and c0.card_id = $2), 0)
                            as kills,
                        coalesce((select c1.count from collection c1
                                   where c1.user_id = $1 and c1.card_id = $2), 0)
                        + coalesce((select count(*) from inventory i
                                     where i.user_id = $1 and i.card_id = $2), 0)
                            as copies
                    """,
                    user_id,
                    chosen,
                )
        profile = dict(row)
        profile["card_points"] = int(profile["card_points"]) + int(profile["inv_points"])
        profile["rank"] = int(rank or 1)
        profile["total"] = max(0, int(profile["bonus_points"]))
        profile["upgraded"] = int(profile["upgraded"] or 0)
        for key in (
            "drops",
            "casino_bets",
            "shop_buys",
            "market_deals",
            "gifts_sent",
            "invited",
            "promos",
        ):
            profile[key] = int(profile.get(key) or 0)
        profile["favorite_card_id"] = chosen
        profile["favorite_manual"] = bool(row["favorite_card"])
        profile["favorite_kills"] = int(card_stats["kills"] or 0) if card_stats else 0
        profile["favorite_copies"] = int(card_stats["copies"] or 0) if card_stats else 0
        return profile

    async def set_favorite_card(self, user_id: int, card_id: str) -> None:
        """Ручной выбор любимой карты (перебивает автоматическую)."""
        async with self._p().acquire() as con:
            await con.execute(
                "update players set favorite_card = $2, updated_at = now() "
                "where user_id = $1",
                user_id,
                card_id,
            )

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

    async def apply_team_result(
        self, winners: list[int], losers: list[int]
    ) -> None:
        """Итог командного боя: +1 победа победителям, +1 поражение проигравшим.

        Ничья/остановка передаёт пустые списки — тогда ничего не меняется.
        """
        winners = [int(uid) for uid in (winners or [])]
        losers = [int(uid) for uid in (losers or [])]
        if not winners and not losers:
            return
        async with self._p().acquire() as con:
            async with con.transaction():
                if winners:
                    await con.execute(
                        "update players set wins = wins + 1 "
                        "where user_id = any($1::bigint[])",
                        winners,
                    )
                if losers:
                    await con.execute(
                        "update players set losses = losses + 1 "
                        "where user_id = any($1::bigint[])",
                        losers,
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

    async def claim_casino(self, user_id: int, day: Any, limit: int = 25) -> int | None:
        """Списывает крутку казино. None — на сегодня круток не осталось."""
        async with self._p().acquire() as con:
            async with con.transaction():
                row = await con.fetchrow(
                    "select casino_day, casino_uses, casino_limit from players "
                    "where user_id = $1 for update",
                    user_id,
                )
                if row is None:
                    return 0
                if row["casino_day"] != day:
                    await con.execute(
                        "update players set casino_day = $2, casino_uses = 0, "
                        "casino_limit = $3 where user_id = $1",
                        user_id,
                        day,
                        limit,
                    )
                    uses, cap = 0, limit
                else:
                    uses = int(row["casino_uses"])
                    cap = max(int(row["casino_limit"]), limit)
                if uses >= cap:
                    return None
                await con.execute(
                    "update players set casino_uses = casino_uses + 1 where user_id = $1",
                    user_id,
                )
                return max(0, cap - uses - 1)

    async def casino_left(self, user_id: int, day: Any, limit: int = 25) -> int:
        """Сколько круток осталось. Ничего не списывает."""
        async with self._p().acquire() as con:
            row = await con.fetchrow(
                "select casino_day, casino_uses, casino_limit from players where user_id = $1",
                user_id,
            )
        if row is None or row["casino_day"] != day:
            return limit
        cap = max(int(row["casino_limit"]), limit)
        return max(0, cap - int(row["casino_uses"]))

    async def casino_stats(self, user_id: int) -> dict[str, int]:
        """Итоги казино игрока: сколько поставил, вернул, выиграл и слил.

        Ставки картами считаются отдельно — у них нет очкового баланса.
        bet_value для очковых ставок — число, поэтому фильтр по bet_kind
        не даёт кастовать card_id.
        """
        async with self._p().acquire() as con:
            row = await con.fetchrow(
                """
                select
                    count(*) filter (where bet_kind = 'points') as point_bets,
                    coalesce(sum(bet_value::bigint)
                             filter (where bet_kind = 'points'), 0) as staked,
                    coalesce(sum(amount)
                             filter (where bet_kind = 'points'), 0) as returned,
                    coalesce(sum(case when amount >= bet_value::bigint
                                      then amount - bet_value::bigint else 0 end)
                             filter (where bet_kind = 'points'), 0) as won_points,
                    coalesce(sum(case when amount < bet_value::bigint
                                      then bet_value::bigint - amount else 0 end)
                             filter (where bet_kind = 'points'), 0) as lost_points,
                    count(*) filter (where bet_kind = 'card') as card_bets,
                    count(*) filter (where bet_kind = 'card' and won) as card_wins,
                    count(*) filter (where bet_kind = 'card' and outcome = 'delete')
                        as card_deleted
                  from casino_log
                 where user_id = $1
                """,
                user_id,
            )
        return {key: int(value or 0) for key, value in dict(row).items()}

    async def buy_casino_spin(
        self, user_id: int, day: Any, price: int, limit: int = 25
    ) -> int | None:
        """Покупает одну крутку казино: атомарно списывает очки и поднимает лимит.

        Возвращает, сколько круток осталось на сегодня, или None, если очков
        не хватает. Важно: покупка сразу проставляет дату, иначе первый же
        claim_casino сбрасывал купленную крутку к дефолтному лимиту.
        """
        async with self._p().acquire() as con:
            async with con.transaction():
                row = await con.fetchrow(
                    "select casino_day, casino_uses, casino_limit, bonus_points "
                    "from players where user_id = $1 for update",
                    user_id,
                )
                if row is None or int(row["bonus_points"]) < int(price):
                    return None
                if row["casino_day"] != day:
                    uses, cap = 0, int(limit)
                else:
                    uses = int(row["casino_uses"])
                    cap = max(int(row["casino_limit"]), int(limit))
                await con.execute(
                    """
                    update players
                       set bonus_points = bonus_points - $2,
                           casino_day = $3,
                           casino_uses = $4,
                           casino_limit = $5,
                           updated_at = now()
                     where user_id = $1
                    """,
                    user_id,
                    int(price),
                    day,
                    uses,
                    cap + 1,
                )
                return cap + 1 - uses

    async def redeem_promo(self, user_id: int, code: str) -> bool:
        """True — промокод принят, False — уже использован."""
        async with self._p().acquire() as con:
            row = await con.fetchrow(
                "insert into promo_uses (user_id, code) values ($1, $2) "
                "on conflict do nothing returning user_id",
                user_id,
                code,
            )
        return row is not None

    # ------------------------------------------------------------------ #
    # Реферальные ссылки
    # ------------------------------------------------------------------ #

    async def latest_ref_link(self, user_id: int) -> dict[str, Any] | None:
        async with self._p().acquire() as con:
            row = await con.fetchrow(
                "select * from ref_links where owner_id = $1 "
                "order by created_at desc, id desc limit 1",
                user_id,
            )
        return dict(row) if row else None

    async def insert_ref_link(
        self, user_id: int, code: str, max_uses: int = 25
    ) -> dict[str, Any]:
        """Создаёт ссылку. ValueError — такой код уже занят."""
        async with self._p().acquire() as con:
            try:
                row = await con.fetchrow(
                    """
                    insert into ref_links (code, owner_id, max_uses)
                    values ($1, $2, $3) returning *
                    """,
                    code,
                    user_id,
                    int(max_uses),
                )
            except asyncpg.UniqueViolationError as error:
                raise ValueError("код ссылки уже занят") from error
        assert row is not None
        return dict(row)

    async def claim_referral(
        self, referred_id: int, code: str
    ) -> dict[str, Any] | None:
        """Фиксирует переход по ссылке. None — ссылка не работает или человек уже приглашён."""
        async with self._p().acquire() as con:
            async with con.transaction():
                already = await con.fetchval(
                    "select 1 from referrals where referred_id = $1", referred_id
                )
                if already:
                    return None
                link = await con.fetchrow(
                    "select * from ref_links where code = $1 for update", code
                )
                if link is None or not link["active"]:
                    return None
                if int(link["uses"]) >= int(link["max_uses"]):
                    return None
                if int(link["owner_id"]) == int(referred_id):
                    return None
                await con.execute(
                    """
                    insert into referrals (referred_id, referrer_id, link_id)
                    values ($1, $2, $3)
                    """,
                    referred_id,
                    int(link["owner_id"]),
                    int(link["id"]),
                )
                uses = int(link["uses"]) + 1
                active = uses < int(link["max_uses"])
                await con.execute(
                    "update ref_links set uses = $2, active = $3 where id = $1",
                    int(link["id"]),
                    uses,
                    active,
                )
                return {
                    "owner_id": int(link["owner_id"]),
                    "uses": uses,
                    "max_uses": int(link["max_uses"]),
                    "exhausted": not active,
                }

    async def my_accessories(self, user_id: int) -> list[dict[str, Any]]:
        async with self._p().acquire() as con:
            rows = await con.fetch(
                "select id, item_id, card_id from accessories "
                "where user_id = $1 order by item_id, id",
                user_id,
            )
        out = []
        for row in rows:
            item = next(
                (i for i in _ACCESSORIES if i.id == int(row["item_id"])), None
            )
            out.append(
                {
                    "id": int(row["id"]),
                    "item_id": int(row["item_id"]),
                    "card_id": row["card_id"],
                    "name": item.name if item else str(row["item_id"]),
                    "summary": item.summary if item else "",
                    "bonus": dict(item.bonus) if item else {},
                }
            )
        return out

    async def attach_accessory(self, user_id: int, acc_id: int, card_id: str) -> None:
        async with self._p().acquire() as con:
            await con.execute(
                "update accessories set card_id = $3 where id = $1 and user_id = $2",
                int(acc_id),
                user_id,
                card_id,
            )

    async def detach_accessory(self, user_id: int, acc_id: int) -> None:
        async with self._p().acquire() as con:
            await con.execute(
                "update accessories set card_id = null where id = $1 and user_id = $2",
                int(acc_id),
                user_id,
            )

    async def accessory_bonus(self, user_id: int, card_id: str) -> dict[str, int]:
        """Сумма процентов всех аксессуаров, надетых на эту карту."""
        async with self._p().acquire() as con:
            rows = await con.fetch(
                "select item_id from accessories where user_id = $1 and card_id = $2",
                user_id,
                card_id,
            )
        bonus: dict[str, int] = {}
        for row in rows:
            item = next(
                (i for i in _ACCESSORIES if i.id == int(row["item_id"])), None
            )
            if item is not None:
                bonus = _sum_bonus(bonus, item.bonus)
        return bonus

    async def find_active_team_battles(self, user_id: int) -> list[dict[str, Any]]:
        """Активные командные бои, где игрок участник — для команды «стоп»."""
        async with self._p().acquire() as con:
            rows = await con.fetch(
                """
                select b.* from battles b
                 where b.status in ('choosing', 'active')
                   and exists (
                       select 1 from jsonb_array_elements(b.state->'participants') p
                        where (p->>'user_id')::bigint = $1
                   )
                 order by b.updated_at desc
                """,
                user_id,
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
