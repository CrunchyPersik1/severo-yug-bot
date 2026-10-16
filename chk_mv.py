
import asyncio, os, sys, urllib.parse
sys.path.insert(0, ".")
DSN = "postgresql://" + urllib.parse.quote("postgres.mcobvefvmlwdxludagkf", safe="") + ":" + urllib.parse.quote("mas7aEdziuNoWiGJ", safe="") + "@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"
os.environ["BOT_TOKEN"] = "8835185511:AAG_TTsJmLf1fN4v6DCcBP3SKABNR7l86-Y"
os.environ["DATABASE_URL"] = DSN
from app.db import Database

async def main():
    db = Database(DSN); await db.connect()
    out = []
    async with db.pool.acquire() as con:
        for row in await con.fetch("select id, name, price, base_price, target_price from stocks order by id"):
            hist = await con.fetch(
                "select price from stock_history where stock_id = $1 order by at desc limit 14",
                int(row["id"]))
            tail = [int(h["price"]) for h in hist][::-1]
            uniq = len(set(tail))
            out.append("  %-18s %-6s цель %-5s  двигается: %-4s хвост %s" % (
                row["name"][:18], row["price"], row["target_price"],
                "ДА" if uniq > 1 else "НЕТ", tail[-5:]))
    await db.close()
    with open("mv.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))

asyncio.run(main())
