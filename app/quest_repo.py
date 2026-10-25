"""Квесты: прогресс по счётчикам и выдача награды ровно один раз.

Прогресс читаем из тех же SQL-счётчиков, что у недельного ивента. Награда
записывается в quest_claim; вставка с on conflict do nothing и есть защита
от двойного нажатия и от двух вкладок сразу.
"""

from __future__ import annotations

import asyncpg

from . import quests
from .db import Database


class QuestError(Exception):
    """Ошибку можно показать игроку."""


class QuestRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    @property
    def pool(self) -> asyncpg.Pool:
        return self.db._p()

    async def list(self, user_id: int) -> list[dict]:
        result: list[dict] = []
        async with self.pool.acquire() as con:
            claimed_rows = await con.fetch(
                "select quest_key from quest_claim where user_id = $1::bigint",
                int(user_id),
            )
            claimed = {str(row["quest_key"]) for row in claimed_rows}
            for index, key in enumerate(quests.order()):
                sql = quests.source_sql(key)
                current = int(await con.fetchval(sql, int(user_id)) or 0) if sql else 0
                need = quests.need_for(key)
                reward = quests.reward_for(key)
                result.append(
                    {
                        "key": key,
                        "title": quests.title_for(key),
                        "need": need,
                        "now": min(current, need),
                        "done": current >= need,
                        "claimed": key in claimed,
                        "reward": reward,
                        "reward_text": quests.reward_text(reward),
                    }
                )
        return result

    async def claim(self, user_id: int, key: object) -> dict:
        name = str(key or "").strip()
        if name not in quests.order():
            raise QuestError("Такого квеста нет")
        index = quests.order().index(name)
        sql = quests.source_sql(name) or ""
        need = quests.need_for(name)

        async with self.pool.acquire() as con:
            async with con.transaction():
                current = int(await con.fetchval(sql, int(user_id)) or 0) if sql else 0
                if current < need:
                    raise QuestError("Квест ещё не выполнен")
                fresh = await con.fetchrow(
                    """
                    insert into quest_claim (user_id, quest_key)
                    values ($1::bigint, $2::text)
                    on conflict (user_id, quest_key) do nothing
                    returning quest_key
                    """,
                    int(user_id),
                    name,
                )
                if fresh is None:
                    raise QuestError("Награда уже получена")
                reward = quests.reward_for(name)
                if reward.get("points"):
                    await con.execute(
                        "update players set bonus_points = bonus_points + $2 "
                        "where user_id = $1::bigint",
                        int(user_id),
                        int(reward["points"]),
                    )
                if reward.get("cases"):
                    await con.execute(
                        "insert into cases (user_id, source) "
                        "select $1::bigint, 'quest' from generate_series(1, $2::integer)",
                        int(user_id),
                        int(reward["cases"]),
                    )
                if reward.get("drops"):
                    await con.execute(
                        "update players set drop_limit = drop_limit + $2 "
                        "where user_id = $1::bigint",
                        int(user_id),
                        int(reward["drops"]),
                    )
                if reward.get("roulette"):
                    await con.execute(
                        "update players set roulette_limit = roulette_limit + $2 "
                        "where user_id = $1::bigint",
                        int(user_id),
                        int(reward["roulette"]),
                    )
                if reward.get("yugi"):
                    await con.execute(
                        """
                        insert into yugi (user_id, balance, total)
                        values ($1::bigint, $2::numeric, $2::numeric)
                        on conflict (user_id) do update
                           set balance = yugi.balance + $2::numeric,
                               total = yugi.total + $2::numeric,
                               updated_at = now()
                        """,
                        int(user_id),
                        int(reward["yugi"]),
                    )
                balance = int(
                    await con.fetchval(
                        "select coalesce(bonus_points, 0) from players "
                        "where user_id = $1::bigint",
                        int(user_id),
                    )
                    or 0
                )
        return {
            "key": name,
            "reward": reward,
            "reward_text": quests.reward_text(reward),
            "balance": balance,
        }
