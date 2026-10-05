
import asyncio, os, sys, urllib.parse
sys.path.insert(0, ".")
from app.db import Database
from app.gacha import day_key, DROPS_PER_DAY
from app.roulette import roulette_day_key, SPINS_PER_DAY

async def main():
    db = Database(os.environ["DATABASE_URL"]); await db.connect()
    uid = 999030
    async with db.pool.acquire() as c:
        await c.execute("delete from players where user_id = $1", uid)
    await db.ensure_player(uid, "g", "Тест")
    async with db.pool.acquire() as c:
        await c.execute("update players set last_drop_day=$1, drop_uses=0, drop_limit=2, roulette_day=$2, roulette_uses=0, roulette_limit=2 where user_id=$3",
                        day_key(), roulette_day_key(), uid)
    res = []
    for i in range(1, 4):
        left = await db.claim_daily(uid, day_key(), DROPS_PER_DAY)
        res.append("карта попытка %d -> остаток %s" % (i, left))
    for i in range(1, 4):
        left = await db.claim_roulette(uid, roulette_day_key(), SPINS_PER_DAY)
        res.append("спин попытка %d -> остаток %s" % (i, left))
    # имитация нового дня: лимит должен вернуться к 1
    async with db.pool.acquire() as c:
        await c.execute("update players set last_drop_day = $1 where user_id = $2", day_key(), uid)
    left = await db.claim_daily(uid, day_key(), DROPS_PER_DAY)
    async with db.pool.acquire() as c:
        row = await c.fetchrow("select drop_uses, drop_limit from players where user_id=$1", uid)
    res.append("следующий день -> остаток %s, лимит вернулся к %s" % (left, row["drop_limit"]))
    async with db.pool.acquire() as c:
        await c.execute("delete from players where user_id = $1", uid)
    await db.close()
    with open("grant_check.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(res))

asyncio.run(main())
