
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
out = []
def probe(uid, name, label):
    raw = init_data(uid, name)
    cmd = ["curl.exe", "-s", "-m", "45", "-w", "\n__C__%{http_code}",
           "-H", "X-Telegram-Init-Data: " + raw, BASE + "/api/hub"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    body = r.stdout or ""
    code = ""
    if "__C__" in body:
        body, _, code = body.rpartition("__C__")
    err = ""
    try:
        d = json.loads(body.strip())
        if isinstance(d, dict) and "error" in d:
            err = " | " + str(d["error"])[:60]
    except Exception:
        err = " | не JSON"
    out.append("  %-28s HTTP %s%s" % (label, code.strip(), err))

out.append("проба /api/hub:")
probe(1806176773, "КранчиПерсик", "админ (нормальный игрок)")
probe(8268218239, "sleepy", "sleepy (ЗАБАНЕН)")
probe(8994104688, "v", "v (ЗАБАНЕН)")
with open("ban.txt", "w", encoding="utf-8") as fh:
    fh.write("\n".join(out))
