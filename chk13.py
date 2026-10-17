
import asyncio, os, sys, urllib.parse
sys.path.insert(0, ".")
DSN = "postgresql://" + urllib.parse.quote("postgres.mcobvefvmlwdxludagkf", safe="") + ":" + urllib.parse.quote("mas7aEdziuNoWiGJ", safe="") + "@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"
os.environ["BOT_TOKEN"] = "8835185511:AAG_TTsJmLf1fN4v6DCcBP3SKABNR7l86-Y"
os.environ["DATABASE_URL"] = DSN
from app.db import Database

async def main():
    db = Database(DSN); await db.connect(); await db.init_schema()
    out = []
    async with db.pool.acquire() as con:
        row = await con.fetchrow(
            "select user_id, first_name, username, bonus_points from players "
            "where username = 'sleepyUsa'")
        if row is None:
            out.append("sleepyUsa не найден")
        else:
            out.append("нашёл: %s (@%s), очков %s" % (
                row["first_name"], row["username"], row["bonus_points"]))
            await db.set_ban(int(row["user_id"]), True, "накрутка очков")
            info = await db.ban_info(int(row["user_id"]))
            out.append("бан: %s, причина: %s" % (info.get("banned"), info.get("ban_reason")))
        banned = await con.fetch("select first_name, username, ban_reason from players where banned = true")
        out.append("")
        out.append("всего забанено: %s" % len(banned))
        for b2 in banned:
            out.append("  %s @%s — %s" % (b2["first_name"], b2["username"], b2["ban_reason"]))
    await db.close()
    with open("bn.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))

asyncio.run(main())
