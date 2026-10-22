
import asyncio, os, sys, urllib.parse
sys.path.insert(0, ".")
DSN = "postgresql://" + urllib.parse.quote("postgres.mcobvefvmlwdxludagkf", safe="") + ":" + urllib.parse.quote("mas7aEdziuNoWiGJ", safe="") + "@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"
os.environ["BOT_TOKEN"] = "8835185511:AAG_TTsJmLf1fN4v6DCcBP3SKABNR7l86-Y"
os.environ["DATABASE_URL"] = DSN
from app.casino_repo import CasinoRepo
from app.db import Database
from app.market_repo import MarketRepo

async def main():
    db = Database(DSN); await db.connect(); await db.init_schema()
    market = MarketRepo(db)
    repo = CasinoRepo(db, market)
    uid = 999955
    out = []
    async with db.pool.acquire() as c:
        await c.execute("delete from players where user_id = $1", uid)
        await c.execute("delete from cases where user_id = $1", uid)
    await db.ensure_player(uid, "vipt", "Вип")
    out.append("до выдачи: vip=%s" % ((await db.vip_info(uid))["active"]))
    out.append("потолок ставки: %s" % await repo._max_bet(uid))
    until = await db.vip_set(uid, 30)
    info = await db.vip_info(uid)
    out.append("после выдачи: vip=%s до %s" % (info["active"], info["until"]))
    out.append("потолок ставки: %s (ждём 1000000)" % await repo._max_bet(uid))
    g = await db.vip_daily(uid)
    out.append("дневные бонусы: %s" % g)
    g2 = await db.vip_daily(uid)
    out.append("повторно в тот же день: %s (ждём None)" % g2)
    async with db.pool.acquire() as c:
        cases = await c.fetchval("select count(*) from cases where user_id = $1", uid)
        row = await c.fetchrow("select drop_limit, roulette_limit from players where user_id = $1", uid)
    out.append("кейсов выдано: %s (ждём 2)" % cases)
    out.append("лимит дропов: %s, лимит спинов: %s" % (row["drop_limit"], row["roulette_limit"]))
    async with db.pool.acquire() as c:
        await c.execute("delete from cases where user_id = $1", uid)
        await c.execute("delete from players where user_id = $1", uid)
    out.append("уборка ок")
    await db.close()
    with open("vip.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))

asyncio.run(main())
