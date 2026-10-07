"""Telegram Mini App: магазин.

Отдаётся тем же FastAPI, что и вебхук, — отдельный хостинг не нужен.
Доступ проверяется подписью initData от Telegram, иначе любой мог бы
дёрнуть /api/buy и купить учителя за один балл.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .cards import get_card
from .items import ACCESSORIES
from .shop import ShopError, catalog

log = logging.getLogger(__name__)

router = APIRouter()


# --------------------------------------------------------------------------- #
# Проверка подписи Telegram
# --------------------------------------------------------------------------- #


def check_init_data(init_data: str, bot_token: str) -> dict[str, Any] | None:
    """Возвращает данные игрока, если подпись настоящая."""
    if not init_data:
        return None
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", None)
    if not received:
        return None
    data_check = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, received):
        return None
    try:
        return json.loads(pairs.get("user", "{}"))
    except ValueError:
        return None


async def _player(request: Request) -> dict[str, Any]:
    state = request.app.state
    raw = request.headers.get("X-Telegram-Init-Data", "")
    user = check_init_data(raw, state.settings.bot_token)
    if user is None or not user.get("id"):
        raise ShopError("Открой магазин через кнопку в боте.")
    user_id = int(user["id"])
    await state.db.ensure_player(
        user_id, user.get("username"), user.get("first_name")
    )
    return user


def _entry_payload(entry) -> dict[str, Any]:
    data: dict[str, Any] = {
        "sku": entry.sku,
        "kind": entry.kind,
        "title": entry.title,
        "subtitle": entry.subtitle,
        "price": entry.price,
    }
    if entry.kind == "card":
        card = get_card(str(entry.payload["card_id"]))
        data["card"] = {
            "emoji": card.rarity_emoji,
            "rarity": card.rarity_title,
            "hp": card.hp,
            "atk": card.atk,
            "ability": card.ability.name,
            "cooldown": card.ability.cooldown,
        }
    elif entry.kind == "pack":
        data["pack"] = [
            {
                "name": get_card(str(cid)).display_name,
                "emoji": get_card(str(cid)).rarity_emoji,
                "hp": get_card(str(cid)).hp,
                "atk": get_card(str(cid)).atk,
            }
            for cid in entry.payload["cards"]
        ]
    elif entry.kind == "accessory":
        item_id = int(entry.payload["item_id"])
        data["icon"] = ACCESSORIES[item_id - 1].name and "🎁"
    return data


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #


@router.get("/api/shop")
async def api_shop(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    balance = await state.shop.balance(int(user["id"]))
    owned = await state.shop.my_accessories(int(user["id"]))
    return JSONResponse(
        {
            "me": {
                "id": int(user["id"]),
                "name": user.get("first_name") or "игрок",
                "balance": balance,
                "accessories": owned,
            },
            "items": [_entry_payload(entry) for entry in catalog()],
        }
    )


@router.post("/api/buy")
async def api_buy(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
        body = await request.json()
        sku = str(body.get("sku", ""))
        result = await state.shop.buy(int(user["id"]), sku)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    except Exception:  # noqa: BLE001
        log.exception("Покупка в мини-аппе упала")
        return JSONResponse({"error": "Не получилось, попробуй ещё"}, status_code=500)

    return JSONResponse(
        {
            "ok": True,
            "balance": result["balance"],
            "granted": result["granted"],
            "title": result["entry"].title,
        }
    )


@router.get("/app", response_class=HTMLResponse)
async def mini_app() -> HTMLResponse:
    return HTMLResponse(PAGE)

PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Северо-Юг · Магазин</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{
  --leaf:#c2410c; --leaf2:#ea580c; --bark:#7c2d12; --cream:#fffbf5;
  --paper:#ffedd5; --ink:#43230f; --muted:#9a6b4f; --ok:#15803d; --bad:#b91c1c;
  --line:#e7c9a9;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0}
body{
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:linear-gradient(180deg,#fffaf3 0%,#ffedd5 40%,#fcd9ae 100%);
  background-attachment:fixed;color:var(--ink);min-height:100vh;padding-bottom:96px;
}
.leafbar{font-size:20px;letter-spacing:6px;text-align:center;padding:10px 0 2px;opacity:.75}
header{padding:6px 18px 14px;text-align:center}
h1{margin:0;font-size:21px;letter-spacing:.3px}
h1 small{display:block;font-weight:400;font-size:12px;color:var(--muted);margin-top:4px;letter-spacing:1.5px;text-transform:uppercase}
.wallet{
  display:inline-flex;align-items:center;gap:8px;margin-top:12px;
  background:linear-gradient(135deg,#fff 0%,#ffedd5 100%);
  border:1px solid var(--line);border-radius:999px;padding:9px 18px;
  font-weight:700;font-size:17px;box-shadow:0 4px 14px rgba(194,65,12,.12)
}
.tabs{display:flex;gap:8px;padding:0 16px 14px;overflow-x:auto;scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}
.tab{
  flex:0 0 auto;border:1px solid var(--line);background:var(--cream);
  color:var(--muted);border-radius:999px;padding:9px 16px;font-size:14px;
  font-weight:600;transition:.15s
}
.tab.on{background:linear-gradient(135deg,var(--leaf2),var(--leaf));color:#fff;border-color:transparent;box-shadow:0 4px 12px rgba(194,65,12,.3)}
main{padding:0 16px}
.card{
  background:var(--cream);border:1px solid var(--line);border-radius:18px;
  padding:14px 15px;margin-bottom:12px;position:relative;overflow:hidden;
  box-shadow:0 3px 12px rgba(124,45,18,.07)
}
.card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:5px;
  background:linear-gradient(180deg,var(--leaf2),var(--leaf))}
.row{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}
.name{font-weight:700;font-size:16px;line-height:1.25}
.rar{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-top:3px}
.role{font-size:13px;color:var(--muted);margin-top:6px;line-height:1.35}
.stats{display:flex;gap:14px;margin-top:9px;font-size:13px;font-weight:600;color:var(--bark)}
.price{font-weight:800;font-size:16px;color:var(--leaf);white-space:nowrap}
.buy{
  margin-top:12px;width:100%;border:0;border-radius:13px;padding:13px;
  font-size:15px;font-weight:700;color:#fff;
  background:linear-gradient(135deg,var(--leaf2),var(--leaf));
  box-shadow:0 5px 14px rgba(194,65,12,.28);transition:.15s
}
.buy:active{transform:scale(.985)}
.buy[disabled]{background:#e5d5c5;color:#a1846c;box-shadow:none}
.pack{font-size:13px;margin-top:8px;padding-left:2px;color:var(--bark);line-height:1.6}
.empty{text-align:center;color:var(--muted);padding:40px 20px;font-size:14px}
#toast{
  position:fixed;left:14px;right:14px;bottom:18px;background:var(--ink);color:#fff;
  border-radius:14px;padding:14px 16px;font-size:14px;line-height:1.45;
  transform:translateY(140%);transition:.28s cubic-bezier(.2,.8,.3,1);z-index:9
}
#toast.on{transform:translateY(0)}
#toast.ok{background:linear-gradient(135deg,#15803d,#166534)}
#toast.bad{background:linear-gradient(135deg,#b91c1c,#991b1b)}
</style>
</head>
<body>
<div class="leafbar">🍁 🍂 🍁 🍂 🍁</div>
<header>
  <h1>Северо-Юг<small>Школьная осень · магазин</small></h1>
  <div class="wallet">🍁 <span id="balance">…</span></div>
</header>
<div class="tabs" id="tabs"></div>
<main id="list"><div class="empty">Загружаю ассортимент…</div></main>
<div id="toast"></div>
<script>
const tg = window.Telegram ? window.Telegram.WebApp : null;
const headers = {"X-Telegram-Init-Data": tg ? tg.initData : ""};
let state = {items: [], tab: "card", balance: 0};
const TABS = [["card","Учителя"],["pack","Наборы"],["accessory","Аксессуары"]];

function money(n){ return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, " "); }

function toast(text, kind){
  const el = document.getElementById("toast");
  el.textContent = text;
  el.className = "on " + (kind || "");
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.className = ""; }, 3200);
}

function renderTabs(){
  document.getElementById("tabs").innerHTML = TABS.map(([key,title]) =>
    '<button class="tab' + (state.tab === key ? ' on' : '') + '" data-tab="' + key + '">' + title + '</button>'
  ).join("");
  document.querySelectorAll(".tab").forEach(b => b.onclick = () => {
    state.tab = b.dataset.tab; renderTabs(); renderList();
  });
}

function cardHtml(it){
  const c = it.card;
  const stats = c ? '<div class="stats"><span>❤️ ' + c.hp + '</span><span>⚔️ ' + c.atk +
    '</span><span>✨ ' + c.ability + ' (КД ' + c.cooldown + ')</span></div>' : "";
  const pack = it.pack ? '<div class="pack">' + it.pack.map(p =>
    p.emoji + " " + p.name + " — ❤️" + p.hp + " ⚔️" + p.atk).join("<br>") + '</div>' : "";
  const enough = state.balance >= it.price;
  return '<div class="card">' +
    '<div class="row"><div><div class="name">' + it.title + '</div>' +
    '<div class="rar">' + (c ? c.emoji + " " + c.rarity : "набор") + '</div>' +
    '<div class="role">' + it.subtitle + '</div></div>' +
    '<div class="price">' + money(it.price) + '</div></div>' +
    stats + pack +
    '<button class="buy" data-sku="' + it.sku + '"' + (enough ? "" : " disabled") + '>' +
    (enough ? "Купить" : "Не хватает очков") + '</button></div>';
}

function renderList(){
  const items = state.items.filter(i => i.kind === state.tab);
  document.getElementById("list").innerHTML = items.length
    ? items.map(cardHtml).join("")
    : '<div class="empty">Тут пока пусто</div>';
  document.querySelectorAll(".buy").forEach(b => b.onclick = () => buy(b));
}

async function load(){
  try{
    const r = await fetch("/api/shop", {headers});
    const data = await r.json();
    if(data.error){ toast(data.error, "bad"); return; }
    state.items = data.items;
    state.balance = data.me.balance;
    document.getElementById("balance").textContent = money(state.balance);
    renderTabs(); renderList();
  }catch(e){ toast("Не смог загрузить магазин", "bad"); }
}

async function buy(btn){
  const sku = btn.dataset.sku;
  btn.disabled = true;
  btn.textContent = "Покупаю…";
  try{
    const r = await fetch("/api/buy", {
      method: "POST",
      headers: Object.assign({"Content-Type":"application/json"}, headers),
      body: JSON.stringify({sku})
    });
    const data = await r.json();
    if(data.error){ toast(data.error, "bad"); }
    else{
      state.balance = data.balance;
      document.getElementById("balance").textContent = money(state.balance);
      toast("🍁 " + data.title + " — твоё! Получено: " + data.granted.join(", "), "ok");
      if(tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
    }
  }catch(e){ toast("Связь потерялась, попробуй ещё", "bad"); }
  renderList();
}

if(tg){ tg.ready(); tg.expand(); }
load();
</script>
</body>
</html>
"""
