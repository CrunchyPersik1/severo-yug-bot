
import hashlib, hmac, json, time, urllib.parse, subprocess
TOKEN = "8835185511:AAG_TTsJmLf1fN4v6DCcBP3SKABNR7l86-Y"
def init_data(uid, name):
    data = {"auth_date": str(int(time.time())), "query_id": "AAt",
            "user": json.dumps({"id": uid, "first_name": name}, separators=(",", ":"))}
    check = "\n".join("%s=%s" % (k, data[k]) for k in sorted(data))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(data)
raw = init_data(1806176773, "КранчиПерсик")
r = subprocess.run(["curl.exe", "-s", "-m", "60", "-H", "X-Telegram-Init-Data: " + raw,
                    "https://severo-yug-bot-zd73.onrender.com/api/yugi"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
out = []
try:
    d = json.loads((r.stdout or "{}").strip())
    if "error" in d:
        out.append("ОШИБКА: " + str(d["error"])[:150])
    else:
        out.append("старых полей: %s" % len([k for k in d if k not in ("tree_pool","upgrades_pool")]))
        out.append("зданий в ответе: %s" % len(d.get("buildings") or []))
        out.append("фишек: %s" % d.get("chips"))
        out.append("узлов древа в пуле: %s" % len(d.get("tree_pool") or []))
        out.append("апгрейдов в пуле: %s" % len(d.get("upgrades_pool") or []))
        out.append("печенька: %s" % (d.get("golden") or {}))
except Exception as e:
    out.append("не разобрал: %s | %s" % (e, (r.stdout or "")[:200]))
open("yg.txt", "w", encoding="utf-8").write("\n".join(out))
