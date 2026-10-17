
import hashlib, hmac, json, time, urllib.parse, subprocess
TOKEN = "8835185511:AAG_TTsJmLf1fN4v6DCcBP3SKABNR7l86-Y"
def init_data(uid, name):
    data = {"auth_date": str(int(time.time())), "query_id": "AAt",
            "user": json.dumps({"id": uid, "first_name": name}, separators=(",", ":"))}
    check = "\n".join("%s=%s" % (k, data[k]) for k in sorted(data))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(data)

BASE = "https://severo-yug-bot.onrender.com"
raw = init_data(1806176773, "КранчиПерсик")
out = []
r = subprocess.run(["curl.exe", "-s", "-m", "60", "-H", "X-Telegram-Init-Data: " + raw,
                    BASE + "/api/case"], capture_output=True, text=True, encoding="utf-8", errors="replace")
try:
    d = json.loads((r.stdout or "").strip())
    out.append("кейсов у тебя: %s" % d.get("cases"))
    n = min(3, int(d.get("cases") or 0))
except Exception as e:
    out.append("не прочитал /api/case: %s" % e); n = 0

if n:
    rr = subprocess.run(["curl.exe", "-s", "-m", "60", "-X", "POST",
                         "-H", "X-Telegram-Init-Data: " + raw,
                         "-H", "Content-Type: application/json",
                         "-d", json.dumps({"count": n}),
                         BASE + "/api/case/open_many"],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        d2 = json.loads((rr.stdout or "").strip())
        if "error" in d2:
            out.append("ОШИБКА: " + str(d2["error"])[:120])
        else:
            out.append("открыл разом: %s кейсов" % len(d2["cards"]))
            for c in d2["cards"]:
                out.append("  %-22s %-18s +%s очк.%s" % (
                    c["name"], c["rarity_title"], c["points"],
                    "  НОВАЯ" if c.get("is_new") else ""))
            out.append("осталось кейсов: %s" % d2["cases"])
    except Exception as e:
        out.append("не разобрал open_many: %s | %s" % (e, (rr.stdout or "")[:150]))
with open("mm.txt", "w", encoding="utf-8") as fh:
    fh.write("\n".join(out))
