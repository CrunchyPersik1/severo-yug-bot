
import asyncio, os, sys, urllib.parse
sys.path.insert(0, ".")
DSN = "postgresql://" + urllib.parse.quote("postgres.mcobvefvmlwdxludagkf", safe="") + ":" + urllib.parse.quote("mas7aEdziuNoWiGJ", safe="") + "@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"
os.environ["BOT_TOKEN"] = "8835185511:AAG_TTsJmLf1fN4v6DCcBP3SKABNR7l86-Y"
os.environ["DATABASE_URL"] = DSN
from app.db import Database

A, B = 999880, 999881

async def main():
    db = Database(DSN); await db.connect(); await db.init_schema()
    out = []
    for u in (A, B):
        async with db.pool.acquire() as c:
            await c.execute("delete from players where user_id=$1", u)
            await c.execute("delete from cases where user_id=$1", u)
        await db.ensure_player(u, "p%s" % u, "PvP%s" % u)
    async with db.pool.acquire() as c:
        await c.execute("update players set bonus_points = 1000000 where user_id = any($1::bigint[])", [A, B])
        await c.execute("insert into cases (user_id, source) select $1,'test' from generate_series(1,10)", A)
    out.append("до боёв: A очки 1 000 000, кейсов 10")
    for i in range(1, 12):
        await db.apply_battle_result(A, B)
        if i in (3, 10, 11):
            async with db.pool.acquire() as c:
                pa = await c.fetchrow("select bonus_points, pvp_streak from players where user_id=$1", A)
                pb = await c.fetchrow("select bonus_points, pvp_streak from players where user_id=$1", B)
                ca = await c.fetchval("select count(*) from cases where user_id=$1 and opened=false", A)
                fights = await c.fetchval("select fights from pvp_pairs where a_id=$1 and b_id=$2", min(A,B), max(A,B))
            out.append("бой %2d: A стрик %s, очки %s, кейсов %s | B очки %s | пара: %s" % (
                i, pa["pvp_streak"], pa["bonus_points"], ca, pb["bonus_points"], fights))
    out.append("")
    out.append("ожидали: стрик 3 -> +5 кейсов, 10 -> +15, на 11-м бою штраф")
    for u in (A, B):
        async with db.pool.acquire() as c:
            await c.execute("delete from cases where user_id=$1", u)
            await c.execute("delete from players where user_id=$1", u)
    async with db.pool.acquire() as c:
        await c.execute("delete from pvp_pairs where a_id=$1 and b_id=$2", min(A,B), max(A,B))
    out.append("уборка ок")
    await db.close()
    with open("pv.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))

asyncio.run(main())
