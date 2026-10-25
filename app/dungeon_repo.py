"""Кооп-босс подземелья: комнаты, удары и состояние боя в транзакциях.

Бой симулируется лениво: никакого планировщика нет, удары босса досчитываются
в момент, когда кто-то читает состояние. Так же живёт кликер в yugi.

Параметры в SQL идут с явными кастами: без них Postgres ругается «could not
determine data type of parameter» (на этом уже один раз зависла биржа).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import asyncpg

from . import dungeon
from .db import Database

# Статусы комнаты:
#   waiting — ждём второго игрока, бой начнётся по времени ready_at
#   fight   — бьёмся
#   dead    — босс повержен
#   failed  — все пали
#   closed  — комната брошена
OPEN_STATUSES = ("waiting", "fight")
FINAL_STATUSES = ("dead", "failed")


class DungeonError(Exception):
    """Ошибку можно показать игроку."""


class DungeonBossRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    @property
    def pool(self) -> asyncpg.Pool:
        return self.db._p()

    # ------------------------------------------------------------------ #
    # Публичное API
    # ------------------------------------------------------------------ #

    async def join(self, user_id: int, zone: object, now: datetime) -> dict:
        """Открыть комнату или зайти во вторую половину чужой."""
        zone_number = dungeon.clamp_zone(zone)
        async with self.pool.acquire() as con:
            async with con.transaction():
                # Два игрока ждут ровно 10 секунд и жмут «в бой» почти
                # одновременно. Без блокировки на локацию оба не видят
                # комнату друг друга и создают по своей — каждый дерётся
                # один. Блокировка держится до конца транзакции.
                await con.execute(
                    "select pg_advisory_xact_lock($1::bigint)",
                    dungeon.zone_lock(zone_number),
                )
                current = await self._room_for(con, user_id)
                if current is not None:
                    boss = await self._advance(con, current["id"], now)
                    if boss is not None and boss["status"] in OPEN_STATUSES:
                        await self._touch(con, boss["id"], user_id, now)
                        return await self._payload(con, boss, user_id, now)

                # Ждущая комната любой давности и бой, который только что
                # начался: и туда, и туда можно сесть вторым.
                partner_room = await self._find_open(con, zone_number, user_id, now)
                if partner_room is not None:
                    partner_room = await self._advance(con, partner_room["id"], now)
                if partner_room is not None and partner_room["status"] in OPEN_STATUSES:
                    seats = await con.fetchval(
                        "select count(*) from dungeon_boss_players "
                        "where boss_id = $1::bigint and left_at is null",
                        partner_room["id"],
                    )
                    seats = int(seats or 0)
                    if seats < dungeon.MAX_PLAYERS:
                        await con.execute(
                            """
                            insert into dungeon_boss_players
                                (boss_id, user_id, slot, hp, max_hp, seen_at)
                            values ($1::bigint, $2::bigint, $3::integer,
                                    $4::integer, $4::integer, $5::timestamptz)
                            on conflict (boss_id, user_id) do update
                               set left_at = null,
                                   dead = false,
                                   hp = dungeon_boss_players.max_hp,
                                   slot = excluded.slot,
                                   seen_at = excluded.seen_at
                            """,
                            partner_room["id"],
                            user_id,
                            seats + 1,
                            dungeon.PLAYER_HP,
                            now,
                        )
                        if partner_room["status"] == "fight":
                            await self._grow_boss(
                                con, partner_room["id"], zone_number, seats + 1, now
                            )
                            await con.execute(
                                "update dungeon_boss_players "
                                "set last_boss_hit_at = $2::timestamptz, "
                                "seen_at = $2::timestamptz "
                                "where boss_id = $1::bigint and user_id = $3::bigint",
                                partner_room["id"],
                                now,
                                user_id,
                            )
                        else:
                            await con.execute(
                                """
                                update dungeon_boss
                                   set status = 'fight',
                                       started_at = $2::timestamptz,
                                       hp = $3::bigint,
                                       max_hp = $3::bigint,
                                       updated_at = $2::timestamptz
                                 where id = $1::bigint and status = 'waiting'
                                """,
                                partner_room["id"],
                                now,
                                dungeon.base_hp(zone_number, seats + 1),
                            )
                            # расписание ударов босса — общее, с этого момента
                            await con.execute(
                                "update dungeon_boss_players "
                                "set last_boss_hit_at = $2::timestamptz, "
                                "seen_at = $2::timestamptz where boss_id = $1::bigint",
                                partner_room["id"],
                                now,
                            )
                        boss = await self._reload(con, partner_room["id"])
                        return await self._payload(con, boss, user_id, now)

                row = await con.fetchrow(
                    """
                    insert into dungeon_boss (zone, hp, max_hp, status, ready_at)
                    values ($1::integer, $2::bigint, $2::bigint, 'waiting',
                            $3::timestamptz)
                    returning *
                    """,
                    zone_number,
                    dungeon.base_hp(zone_number, 1),
                    now + timedelta(seconds=dungeon.WAIT_SECONDS),
                )
                await con.execute(
                    """
                    insert into dungeon_boss_players
                        (boss_id, user_id, slot, hp, max_hp, seen_at)
                    values ($1::bigint, $2::bigint, 1, $3::integer, $3::integer,
                            $4::timestamptz)
                    """,
                    row["id"],
                    user_id,
                    dungeon.PLAYER_HP,
                    now,
                )
                return await self._payload(con, row, user_id, now)

    async def start_now(self, user_id: int, now: datetime) -> dict:
        """Начать бой, не дожидаясь конца окна: «в бой один»."""
        async with self.pool.acquire() as con:
            async with con.transaction():
                room = await self._room_for(con, user_id)
                if room is None:
                    raise DungeonError("Боя нет — подойди к боссу")
                if room["status"] == "waiting":
                    await con.execute(
                        "update dungeon_boss set ready_at = $2::timestamptz, "
                        "updated_at = $2::timestamptz where id = $1::bigint "
                        "and status = 'waiting'",
                        room["id"],
                        now,
                    )
                boss = await self._advance(con, room["id"], now)
                if boss is None:
                    return {"status": "none"}
                await self._touch(con, boss["id"], user_id, now)
                return await self._payload(con, boss, user_id, now)

    async def state(self, user_id: int, now: datetime) -> dict:
        """Текущее состояние комнаты игрока, с досчитанными ударами босса."""
        async with self.pool.acquire() as con:
            async with con.transaction():
                room = await self._room_for(con, user_id)
                if room is None:
                    return {"status": "none"}
                boss = await self._advance(con, room["id"], now)
                if boss is None:
                    return {"status": "none"}
                if boss["status"] in OPEN_STATUSES:
                    await self._touch(con, boss["id"], user_id, now)
                return await self._payload(con, boss, user_id, now)

    async def hit(self, user_id: int, damage: object, now: datetime) -> dict:
        """Удар по боссу. Возвращает состояние плюс сколько сняли."""
        async with self.pool.acquire() as con:
            async with con.transaction():
                room = await self._room_for(con, user_id)
                if room is None:
                    raise DungeonError("Боя нет — подойди к боссу")
                boss = await self._advance(con, room["id"], now)
                if boss is None or boss["status"] not in OPEN_STATUSES:
                    payload = await self._payload(con, boss, user_id, now) if boss else {"status": "none"}
                    payload["error"] = "Бой уже закончился"
                    return payload

                player = await con.fetchrow(
                    "select * from dungeon_boss_players "
                    "where boss_id = $1::bigint and user_id = $2::bigint "
                    "for update",
                    boss["id"],
                    user_id,
                )
                if player is None:
                    raise DungeonError("Ты не в этом бою")
                if player["left_at"] is not None:
                    raise DungeonError("Ты вышел из боя")
                if player["dead"]:
                    raise DungeonError("Ты выбыл — товарищ ещё дерётся")

                left = dungeon.cooldown_left(player["last_hit_at"], now)
                if left > 0:
                    payload = await self._payload(con, boss, user_id, now)
                    payload["cooldown"] = round(left, 2)
                    return payload

                dealt = dungeon.clamp_damage(damage)
                hp = max(0, int(boss["hp"]) - dealt)
                await con.execute(
                    """
                    update dungeon_boss
                       set hp = $2::bigint,
                           status = case when $2::bigint <= 0 then 'dead'
                                         else status end,
                           finished_at = case when $2::bigint <= 0 then $3::timestamptz
                                              else finished_at end,
                           updated_at = $3::timestamptz
                     where id = $1::bigint
                    """,
                    boss["id"],
                    hp,
                    now,
                )
                await con.execute(
                    """
                    update dungeon_boss_players
                       set hits = hits + 1,
                           damage = damage + $3::bigint,
                           last_hit_at = $4::timestamptz,
                           seen_at = $4::timestamptz
                     where boss_id = $1::bigint and user_id = $2::bigint
                    """,
                    boss["id"],
                    user_id,
                    dealt,
                    now,
                )
                if hp <= 0:
                    await self._reward_yugi(con, boss["id"], boss["zone"])
                boss = await self._reload(con, boss["id"])
                payload = await self._payload(con, boss, user_id, now)
                payload["hit"] = dealt
                return payload

    async def leave(self, user_id: int, now: datetime) -> dict:
        """Выйти из боя. Комната закрывается, когда в ней никого не осталось."""
        async with self.pool.acquire() as con:
            async with con.transaction():
                room = await self._room_for(con, user_id)
                if room is None:
                    return {"status": "none"}
                await con.execute(
                    """
                    update dungeon_boss_players
                       set left_at = $3::timestamptz,
                           dead = true,
                           seen_at = $3::timestamptz
                     where boss_id = $1::bigint and user_id = $2::bigint
                       and left_at is null
                    """,
                    room["id"],
                    user_id,
                    now,
                )
                alive = await con.fetchval(
                    "select count(*) from dungeon_boss_players "
                    "where boss_id = $1::bigint and left_at is null",
                    room["id"],
                )
                if int(alive or 0) == 0:
                    await con.execute(
                        """
                        update dungeon_boss
                           set status = 'closed',
                               finished_at = coalesce(finished_at, $2::timestamptz),
                               updated_at = $2::timestamptz
                         where id = $1::bigint and status in ('waiting', 'fight')
                        """,
                        room["id"],
                        now,
                    )
                return {"status": "left", "id": int(room["id"])}

    # ------------------------------------------------------------------ #
    # Внутреннее
    # ------------------------------------------------------------------ #

    async def _room_for(self, con: asyncpg.Connection, user_id: int) -> asyncpg.Record | None:
        """Активная комната игрока, а если её нет — только что закончившаяся."""
        row = await con.fetchrow(
            """
            select b.* from dungeon_boss b
              join dungeon_boss_players p on p.boss_id = b.id
             where p.user_id = $1::bigint and p.left_at is null
               and b.status in ('waiting', 'fight')
             order by b.id desc limit 1
            """,
            user_id,
        )
        if row is not None:
            return row
        return await con.fetchrow(
            """
            select b.* from dungeon_boss b
              join dungeon_boss_players p on p.boss_id = b.id
             where p.user_id = $1::bigint and p.left_at is null
               and b.status in ('dead', 'failed')
               and b.finished_at > now() - interval '90 seconds'
             order by b.id desc limit 1
            """,
            user_id,
        )

    async def _find_open(
        self, con: asyncpg.Connection, zone: int, user_id: int, now: datetime
    ) -> asyncpg.Record | None:
        """Комната в этой локации, куда можно сесть вторым.

        Годится любая ожидающая (даже если окно уже истекло — просто ещё
        никто не открывал состояние) и бой, начавшийся не дольше JOIN_GRACE
        назад. for update: второй не сядет в занятую комнату.
        """
        return await con.fetchrow(
            """
            select b.* from dungeon_boss b
             where b.zone = $1::integer
               and b.status in ('waiting', 'fight')
               and (b.status = 'waiting' or b.started_at > $2::timestamptz)
               and (select count(*) from dungeon_boss_players p
                     where p.boss_id = b.id and p.left_at is null) < $3::integer
               and not exists (select 1 from dungeon_boss_players p2
                                where p2.boss_id = b.id and p2.user_id = $4::bigint)
             order by b.id
             limit 1
             for update
            """,
            zone,
            now - timedelta(seconds=dungeon.JOIN_GRACE),
            dungeon.MAX_PLAYERS,
            user_id,
        )

    async def _grow_boss(
        self, con: asyncpg.Connection, boss_id: int, zone: int, players: int,
        now: datetime,
    ) -> None:
        """Напарник подсел на ходу — поднимаем и максимум, и текущее HP."""
        target = dungeon.base_hp(zone, players)
        await con.execute(
            """
            update dungeon_boss
               set max_hp = greatest(max_hp, $2::bigint),
                   hp = least(greatest(max_hp, $2::bigint),
                              hp + greatest(0, $2::bigint - max_hp)),
                   updated_at = $3::timestamptz
             where id = $1::bigint
            """,
            int(boss_id),
            target,
            now,
        )

    async def _reload(self, con: asyncpg.Connection, boss_id: int) -> asyncpg.Record:
        row = await con.fetchrow(
            "select * from dungeon_boss where id = $1::bigint", int(boss_id)
        )
        if row is None:
            raise DungeonError("Бой пропал")
        return row

    async def _touch(
        self, con: asyncpg.Connection, boss_id: int, user_id: int, now: datetime
    ) -> None:
        await con.execute(
            "update dungeon_boss_players set seen_at = $3::timestamptz "
            "where boss_id = $1::bigint and user_id = $2::bigint",
            int(boss_id),
            int(user_id),
            now,
        )

    async def _advance(
        self, con: asyncpg.Connection, boss_id: int, now: datetime
    ) -> asyncpg.Record | None:
        """Догоняет бой до текущего момента: старт по времени, удары босса."""
        boss = await con.fetchrow(
            "select * from dungeon_boss where id = $1::bigint for update",
            int(boss_id),
        )
        if boss is None:
            return None
        if boss["status"] not in OPEN_STATUSES:
            return boss

        players = await con.fetch(
            "select p.*, coalesce(h.armor, 0) as armor from dungeon_boss_players p "
            "left join dungeon_hero h on h.user_id = p.user_id "
            "where p.boss_id = $1::bigint order by p.slot",
            int(boss_id),
        )

        # Брошенная комната: никто не заглядывал дольше IDLE_SECONDS.
        seen = [p["seen_at"] for p in players if p["seen_at"] is not None]
        if seen and (now - max(seen)).total_seconds() > dungeon.IDLE_SECONDS:
            await con.execute(
                "update dungeon_boss set status = 'closed', "
                "finished_at = coalesce(finished_at, $2::timestamptz), "
                "updated_at = $2::timestamptz where id = $1::bigint",
                int(boss_id),
                now,
            )
            return await self._reload(con, boss_id)

        if boss["status"] == "waiting" and now >= boss["ready_at"]:
            # Второй не пришёл — начинаем с теми, кто есть.
            max_hp = dungeon.base_hp(boss["zone"], len(players))
            await con.execute(
                """
                update dungeon_boss
                   set status = 'fight',
                       started_at = $2::timestamptz,
                       hp = $3::bigint,
                       max_hp = $3::bigint,
                       updated_at = $2::timestamptz
                 where id = $1::bigint
                """,
                int(boss_id),
                now,
                max_hp,
            )
            await con.execute(
                "update dungeon_boss_players set last_boss_hit_at = $2::timestamptz "
                "where boss_id = $1::bigint",
                int(boss_id),
                now,
            )
            boss = await self._reload(con, boss_id)
            players = await con.fetch(
                "select * from dungeon_boss_players where boss_id = $1::bigint "
                "order by slot",
                int(boss_id),
            )

        if boss["status"] == "fight":
            damage = dungeon.boss_damage(boss["zone"])
            for player in players:
                if player["dead"] or player["left_at"] is not None:
                    continue
                last = player["last_boss_hit_at"] or boss["started_at"] or now
                ticks = dungeon.ticks_since(last, now, dungeon.BOSS_HIT_EVERY)
                if ticks <= 0:
                    continue
                hurt = damage * ticks
                armor = int(player["armor"]) if "armor" in player else 0
                if armor:
                    hurt = max(1, int(round(hurt * (1 - dungeon.armor_discount(armor)))))
                hp = max(0, int(player["hp"]) - hurt)
                await con.execute(
                    """
                    update dungeon_boss_players
                       set hp = $3::integer,
                           dead = $3::integer <= 0,
                           last_boss_hit_at = $4::timestamptz
                     where boss_id = $1::bigint and user_id = $2::bigint
                    """,
                    int(boss_id),
                    int(player["user_id"]),
                    hp,
                    dungeon.next_tick_at(last, ticks, dungeon.BOSS_HIT_EVERY) or now,
                )
            alive = await con.fetchval(
                "select count(*) from dungeon_boss_players "
                "where boss_id = $1::bigint and dead = false and left_at is null",
                int(boss_id),
            )
            if int(alive or 0) == 0:
                await con.execute(
                    "update dungeon_boss set status = 'failed', "
                    "finished_at = coalesce(finished_at, $2::timestamptz), "
                    "updated_at = $2::timestamptz where id = $1::bigint",
                    int(boss_id),
                    now,
                )
            boss = await self._reload(con, boss_id)
        return boss

    async def _payload(
        self, con: asyncpg.Connection, boss: asyncpg.Record, user_id: int, now: datetime
    ) -> dict:
        """Состояние для страницы: всё, что нужно нарисовать без лишних запросов."""
        rows = await con.fetch(
            """
            select p.*,
                   coalesce(nullif(pl.first_name, ''), pl.username, 'Игрок') as name
              from dungeon_boss_players p
              left join players pl on pl.user_id = p.user_id
             where p.boss_id = $1::bigint
             order by p.slot
            """,
            int(boss["id"]),
        )
        players = []
        me = None
        me_row = None
        for row in rows:
            item = {
                "name": str(row["name"]),
                "slot": int(row["slot"]),
                "hp": int(row["hp"]),
                "max_hp": int(row["max_hp"]),
                "damage": int(row["damage"]),
                "hits": int(row["hits"]),
                "dead": bool(row["dead"]),
                "left": row["left_at"] is not None,
                "me": int(row["user_id"]) == int(user_id),
            }
            players.append(item)
            if item["me"]:
                me = item
                me_row = row
        status = str(boss["status"])
        cooldown = 0.0
        if me_row is not None:
            cooldown = round(dungeon.cooldown_left(me_row["last_hit_at"], now), 2)
        alive = len([p for p in players if not p["left"]]) or 1
        reward = dungeon.boss_reward(boss["zone"], alive) if status == "dead" else None
        return {
            "id": int(boss["id"]),
            "zone": int(boss["zone"]),
            "zone_name": dungeon.zone_name(boss["zone"]),
            "hp": int(boss["hp"]),
            "max_hp": int(boss["max_hp"]),
            "status": status,
            "status_text": dungeon.status_text(status),
            "coop": alive > 1,
            "ready_in": dungeon.ready_in(boss["ready_at"], now) if status == "waiting" else 0,
            "players": players,
            "me": me,
            "cooldown": cooldown,
            "reward": reward,
        }

    async def _reward_yugi(
        self, con: asyncpg.Connection, boss_id: int, zone: int
    ) -> None:
        """Победа над боссом капает Юги в кликер — общая экономика."""
        amount = dungeon.boss_yugi(zone)
        rows = await con.fetch(
            "select user_id from dungeon_boss_players "
            "where boss_id = $1::bigint and left_at is null",
            int(boss_id),
        )
        for row in rows:
            await con.execute(
                """
                insert into yugi (user_id, balance, total)
                values ($1::bigint, $2::numeric, $2::numeric)
                on conflict (user_id) do update
                   set balance = yugi.balance + $2::numeric,
                       total = yugi.total + $2::numeric,
                       updated_at = now()
                """,
                int(row["user_id"]),
                amount,
            )
