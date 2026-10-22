
import asyncio, hashlib, hmac, json, os, sys, time, urllib.parse, subprocess
sys.path.insert(0, ".")
DSN = "postgresql://" + urllib.parse.quote("postgres.mcobvefvmlwdxludagkf", safe="") + ":" + urllib.parse.quote("mas7aEdziuNoWiGJ", safe="") + "@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"
os.environ["BOT_TOKEN"] = "8835185511:AAG_TTsJmLf1fN4v6DCcBP3SKABNR7l86-Y"
os.environ["DATABASE_URL"] = DSN
from app.db import Database

TOKEN = "8835185511:AAG_TTsJmLf1fN4v6DCcBP3SKABNR7l86-Y"
UID = 1806176773
BASE = "https://severo-yug-bot.onrender.com"

def init_data(uid, name):
    data = {"auth_date": str(int(time.time())), "query_id": "AAt",
            "user": json.dumps({"id": uid, "first_name": name}, separators=(",", ":"))}
    check = "\n".join("%s=%s" % (k, data[k]) for k in sorted(data))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(data)

async def main():
    out = []
    db = Database(DSN); await db.connect()
    async with db.pool.acquire() as c:
        await c.execute("insert into cases (user_id, source) select $1,'case_d' from generate_series(1,5)", UID)
    out.append("выдал 5 кейсов 7Д для теста")
    await db.close()
    raw = init_data(UID, "КранчиПерсик")
    r = subprocess.run(["curl.exe", "-s", "-m", "90", "-X", "POST",
                        "-H", "X-Telegram-Init-Data: " + raw,
                        "-H", "Content-Type: application/json",
                        "-d", json.dumps({"count": 5, "kind": "d"}),
                        BASE + "/api/case/open_many"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    d = json.loads((r.stdout or "{}").strip())
    if "error" in d:
        out.append("ОШИБКА: " + str(d["error"])[:120])
    else:
        bad = 0
        for c in d["cards"]:
            ok = str(c["id"]).startswith("d_")
            if not ok: bad += 1
            out.append("  %-22s %-18s %s" % (c["name"], c["rarity_title"], "7Д" if ok else "!!! 7Г !!!"))
        out.append("")
        out.append("чужих карт: %s из %s" % (bad, len(d["cards"])))
        out.append("ИТОГ: " + ("все из 7Д — БАГ ЗАКРЫТ" if bad == 0 else "ЕСТЬ 7Г — НЕ ЗАКРЫТ"))
    with open("chk.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))

asyncio.run(main())
