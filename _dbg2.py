
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
open("err.txt", "w", encoding="utf-8").write((r.stdout or "")[:1600])
