"""Разово выдать всем попытки на сегодня: сбросить кулдауны и поднять лимит.

    python scripts/grant_daily.py 2 2     # по 2 карты и по 2 спина каждому
    python scripts/grant_daily.py         # просто сбросить кулдауны

Лимит действует только на текущие сутки: при следующей смене дня он вернётся
к дефолтному (1 карта в 12:00 ЕКБ, 1 спин в 20:00 ЕКБ).
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.db import Database  # noqa: E402
from app.gacha import day_key  # noqa: E402
from app.roulette import roulette_day_key  # noqa: E402


async def main() -> None:
    drops = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    spins = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("Не задан DATABASE_URL")

    db = Database(dsn)
    await db.connect()
    await db.init_schema()
    try:
        async with db.pool.acquire() as con:
            total = await con.fetchval("select count(*) from players")
            busy = await con.fetchval(
                "select count(*) from players "
                "where drop_uses > 0 or roulette_uses > 0 "
                "  or last_drop_day is not null or roulette_day is not null"
            )
            await con.execute(
                """
                update players
                   set last_drop_day = $1, drop_uses = 0, drop_limit = $3,
                       roulette_day = $2, roulette_uses = 0, roulette_limit = $4,
                       updated_at = now()
                """,
                day_key(),
                roulette_day_key(),
                max(0, drops),
                max(0, spins),
            )
        print(f"игроков: {total}")
        print(f"было с активным кулдауном: {busy}")
        print(f"выдано на сегодня: {drops} карт(ы) и {spins} спин(ов)")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
