"""Telegram Mini App: магазин.

Отдаётся тем же FastAPI, что и вебхук, — отдельный хостинг не нужен.
Доступ проверяется подписью initData от Telegram, иначе любой мог бы
дёрнуть /api/buy и купить учителя за один балл.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import contextlib
import logging
import random
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from . import buyer
from . import casino
from . import depcoins
from . import event_week
from . import profiles
from .market import UPGRADE_PRICE, market_price
from . import levels
from . import dice_casino
from . import themes
from . import cases as cases_mod
from . import roulette as roulette_mod
from . import upgrader
from . import yugi
from .cards import (
    CARDS,
    CARDS_BY_ID,
    UPGRADER_EXCLUDED_CARD_IDS,
    cards_sorted_for_user,
    get_card,
    image_url,
    rarity_name,
)
from .casino_repo import CasinoRepo
from .cases import roll_case_card
from . import dungeon
from .dungeon_repo import DungeonError
from .quest_repo import QuestError
from .games_page import CASE_PAGE, ROULETTE_PAGE
from .webtheme import inject
from .items import ACCESSORIES
from .render import describe_ability
from .roulette import (
    SPINS_PER_DAY,
    next_roulette_reset,
    roll_prize,
    roulette_day_key,
    segment_index,
    wheel_segments,
)
from .shop import ShopError, catalog
from .stocks_repo import StocksError

log = logging.getLogger(__name__)

router = APIRouter()

# Картинки берём прямо из репозитория — в базу не пишем.
IMAGES_DIR = Path(__file__).resolve().parent.parent / "images"


@router.get("/images/{name}")
async def card_image(name: str) -> FileResponse:
    safe = Path(name).name
    path = IMAGES_DIR / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="нет такой картинки")
    return FileResponse(path)


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
    # Бан действует и в мини-аппках, а не только в боте. Раньше забаненный
    # мог спокойно играть через приложение — middleware его не видел.
    if user_id not in state.settings.admin_ids and await state.db.is_banned(user_id):
        raise ShopError("🚫 Доступ закрыт: аккаунт заблокирован.")
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
        image = image_url(card.card_id)
        if image:
            data["image"] = image
        data["card"] = {
            "emoji": card.rarity_emoji,
            "rarity": card.rarity_title,
            "hp": card.hp,
            "atk": card.atk,
            "ability": card.ability.name,
            "cooldown": card.ability.cooldown,
            "description": card.description,
            "effects": describe_ability(card),
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
    elif entry.kind == "theme":
        theme = themes.get(str(entry.payload["theme_id"]))
        data["theme"] = {
            "id": theme.id,
            "bg": theme.bg,
            "panel": theme.panel,
            "panel2": theme.panel2,
            "acc": theme.acc,
            "acc2": theme.acc2,
            "particles": theme.particles,
        }
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
    return HTMLResponse(inject(PAGE))

PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Северо-Юг · Магазин</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{
  --ex-bg:#0e1116; --ex-panel:#161b24; --ex-panel2:#1d2430; --ex-line:#252e3d;
  --ex-line2:#1a2230; --ex-ink:#f2ece5; --ex-muted:#8b93a7;
  --ex-acc:#dc8a3f; --ex-acc2:#efaa5f; --ex-ink-acc:#1b1206;
  --ex-up:#9dc941; --ex-down:#e0407a;
  --mono:'JetBrains Mono',ui-monospace,SFMono-Regular,monospace;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0;overscroll-behavior:none}
body{
  background:#0e1116!important;color:#f2ece5!important;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  min-height:100vh;padding-bottom:190px;
}
body::before{
  content:"";position:fixed;inset:0;z-index:0;pointer-events:none;
  background:radial-gradient(1100px 560px at 85% -12%,#1b2740 0%,#0e1116 58%);
}
/* встроенная тема рисует свою шапку — у биржи своя */
#__back{display:none!important}
.wrap{position:relative;z-index:1;max-width:560px;margin:0 auto}

/* ---------- шапка ---------- */
header.top{
  position:sticky;top:0;z-index:9;display:flex;align-items:center;gap:10px;
  padding:14px 15px;background:#0e1116e6!important;
  backdrop-filter:blur(14px);border-bottom:1px solid #1a2230!important;
}
header.top .back{
  display:inline-flex;align-items:center;gap:6px;text-decoration:none;
  background:#161b24!important;border:1px solid #252e3d!important;
  border-radius:999px!important;color:#f2ece5!important;padding:8px 14px!important;
  font:800 12px/1 inherit;
}
header.top .ttl{flex:1;text-align:center;font:900 13px/1 inherit;letter-spacing:2.4px;
  color:#f2ece5!important}
.live{display:inline-flex;align-items:center;gap:6px;color:#9dc941!important;
  font:700 10px/1 var(--mono);letter-spacing:1.2px}
.live i{width:7px;height:7px;border-radius:50%;background:#9dc941;
  box-shadow:0 0 9px #9dc941;animation:expulse 1.8s ease-in-out infinite}
@keyframes expulse{0%,100%{opacity:1}50%{opacity:.25}}

/* ---------- акция ---------- */
.hero{padding:18px 15px 4px}
.hero .nm{font-size:23px;font-weight:900;letter-spacing:-.5px;line-height:1.15;
  color:#f2ece5!important}
.hero .sub{font-size:11.5px;color:#8b93a7!important;margin-top:4px}
.hero .pr{margin-top:14px;font:900 42px/1 var(--mono)!important;
  letter-spacing:-1.8px;font-variant-numeric:tabular-nums;color:#f2ece5!important}
.ch{
  display:inline-flex;align-items:center;gap:6px;margin-top:9px;padding:6px 11px;
  border:0!important;border-radius:999px!important;
  font:800 12px/1 var(--mono)!important;font-variant-numeric:tabular-nums;
}
.ch.up{color:#9dc941!important;background:#9dc9411f!important}
.ch.down{color:#e0407a!important;background:#e0407a1f!important}
.up{color:#9dc941!important}
.down{color:#e0407a!important}

/* ---------- плитки ---------- */
.stats{display:grid;grid-template-columns:1fr 1fr;gap:9px;padding:14px 15px 4px}
.stat{background:#161b24!important;border:1px solid #252e3d!important;
  border-radius:14px!important;padding:11px 13px!important;box-shadow:none!important}
.stat span{display:block;font-size:10px;letter-spacing:1.1px;text-transform:uppercase;
  color:#8b93a7!important;font-weight:800}
.stat b{display:block;margin-top:5px;font:900 16px/1.15 var(--mono)!important;
  font-variant-numeric:tabular-nums;color:#f2ece5!important}

/* ---------- портфель ---------- */
.pf{
  margin:14px 15px 4px;padding:13px 14px;border-radius:16px!important;
  background:#161b24!important;border:1px solid #252e3d!important;
  position:relative;overflow:hidden;box-shadow:none!important;
}
.pf::before{
  content:"";position:absolute;left:0;top:12px;bottom:12px;width:3px;
  border-radius:0 3px 3px 0;background:#dc8a3f;
}
.pf .pt{padding-left:10px;font-size:10px;letter-spacing:1.4px;text-transform:uppercase;
  color:#8b93a7!important;font-weight:800}
.pf .pr{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:11px;
  padding-left:10px}
.pf .pr>div{display:flex;flex-direction:column;gap:4px;min-width:0}
.pf .pr span{font-size:9.5px;letter-spacing:.8px;text-transform:uppercase;
  color:#8b93a7!important;font-weight:800}
.pf .pr b{font:900 15px/1.15 var(--mono)!important;font-variant-numeric:tabular-nums;
  color:#f2ece5!important}
.pf .sub{padding-left:10px;margin-top:10px;font-size:11px;color:#8b93a7!important;
  line-height:1.5}

/* ---------- график ---------- */
.chart{padding:14px 15px 0}
.chartbox{background:#12161d!important;border:1px solid #1e2634!important;
  border-radius:16px!important;overflow:hidden;position:relative;box-shadow:none!important}
.charthead{display:flex;justify-content:space-between;align-items:center;
  padding:11px 13px 2px;font-size:10px;letter-spacing:1.3px;color:#8b93a7!important;
  font-weight:800}
#cv{height:240px;width:100%}
.note{padding:10px 15px 0;font-size:11.5px;color:#8b93a7!important;line-height:1.5}

/* ---------- липкая панель сделки ---------- */
.dock{
  position:fixed;left:0;right:0;bottom:0;z-index:14;
  padding:10px 15px calc(12px + env(safe-area-inset-bottom));
  background:linear-gradient(#0e111600,#0e1116f7 40%)!important;
  backdrop-filter:blur(16px);border-top:1px solid #1a2230!important;
}
.stepper{display:flex;gap:7px;margin-bottom:9px;background:none!important}
.stepper button{
  flex:1;border:1px solid #252e3d!important;background:#161b24!important;
  color:#8b93a7!important;border-radius:11px!important;padding:9px 0!important;
  font:800 11px/1 inherit;box-shadow:none!important;
}
.stepper button.on{
  background:#dc8a3f!important;color:#1b1206!important;border-color:#dc8a3f!important;
}
.act{
  display:flex;gap:9px;background:none!important;border:0!important;
  padding:0!important;box-shadow:none!important;border-radius:0!important;
}
.act button{
  flex:1 1 0;min-width:0;width:auto;margin:0;border:0!important;
  border-radius:14px!important;padding:16px!important;
  font:900 15px/1 inherit;letter-spacing:.3px;box-shadow:none!important;
}
.act .buy{background:linear-gradient(#efaa5f,#dc8a3f)!important;color:#1b1206!important;
  box-shadow:0 6px 18px #dc8a3f33!important}
.act .sell{background:#1d2430!important;color:#f2ece5!important;
  border:1px solid #2b3648!important}
.act button[disabled]{opacity:.4!important}

/* ---------- список акций ---------- */
.list{padding:16px 15px 0}
.lhead{font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:#8b93a7!important;
  font-weight:800;padding:0 2px 10px}
.row{
  display:flex;align-items:center;gap:12px;background:#161b24!important;
  border:1px solid #252e3d!important;border-radius:14px!important;
  padding:12px 13px!important;margin-bottom:8px;box-shadow:none!important;
  transition:border-color .15s ease,background .15s ease;
}
.row.on{border-color:#dc8a3f!important;background:#1b2130!important}
.row .av{width:38px;height:38px;border-radius:12px;border:1px solid #252e3d;
  flex:0 0 auto;display:flex;align-items:center;justify-content:center;font-size:17px;
  background:#1d2430}
.row .mid{flex:1;min-width:0}
.row .nm{font-size:14px;font-weight:800;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;color:#f2ece5!important}
.row .mt{font-size:11px;color:#8b93a7!important;margin-top:2px}
.row .rt{text-align:right}
.row .rt b{display:block;font:900 14px/1.1 var(--mono)!important;
  font-variant-numeric:tabular-nums;color:#f2ece5!important}
.row .rt i{display:block;margin-top:3px;font:800 11px/1 var(--mono)!important;
  font-variant-numeric:tabular-nums}

/* ---------- тост ---------- */
#toast{
  position:fixed;left:14px;right:14px;bottom:190px;z-index:30;
  background:#1d2430!important;color:#f2ece5!important;
  border:1px solid #2b3648!important;border-radius:13px!important;
  padding:13px 15px!important;font-size:12.5px;line-height:1.45;box-shadow:none!important;
  transform:translateY(240%);transition:transform .25s ease;
}
#toast.on{transform:translateY(0)}
</style>
</head>
<body>
<div class="leafbar">🍁 🍂 🍁 🍂 🍁</div>
<header>
  <h1>Северо-Юг<small>Школьная осень · магазин</small></h1>
  <div class="wallet"><span id="balance">…</span></div>
</header>
<div class="tabs" id="tabs"></div>
<main id="list"><div class="empty">Загружаю ассортимент…</div></main>
<div id="toast"></div>
<script>
const tg = window.Telegram ? window.Telegram.WebApp : null;
const headers = {"X-Telegram-Init-Data": tg ? tg.initData : ""};
// Вкладка кейса идёт первой: иначе товар не видно ни в одной категории.
const TABS = [["case_d","🏫 Кейс 7Д"],["card","Учителя"],["pack","Наборы"],["accessory","Аксессуары"],["theme","Стили"]];
let state = {items: [], tab: "case_d", balance: 0};

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
    '</span><span>✨ ' + c.ability + ' (КД ' + c.cooldown + ')' +
    (c.effects ? ': ' + c.effects : '') + '</span></div>' : "";
  const pack = it.pack ? '<div class="pack">' + it.pack.map(p =>
    p.emoji + " " + p.name + " — ❤️" + p.hp + " ⚔️" + p.atk).join("<br>") + '</div>' : "";
  const enough = state.balance >= it.price;
  const swatch = it.theme
    ? '<div style="display:flex;gap:5px;margin-top:9px">' +
      ['bg','panel2','acc','acc2'].map(k =>
        '<span style="flex:1;height:16px;border-radius:5px;background:' + it.theme[k] +
        ';border:1px solid rgba(255,255,255,.14)"></span>').join("") + '</div>'
    : "";
  return '<div class="card">' +
    '<div class="row"><div><div class="name">' + it.title + '</div>' +
    '<div class="rar">' + (c ? c.emoji + " " + c.rarity : (it.theme ? "стиль" : "набор")) + '</div>' +
    '<div class="role">' + it.subtitle + '</div></div>' +
    '<div class="price">' + money(it.price) + '</div></div>' +
    stats + pack + swatch +
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
    document.getElementById("balance").textContent = "$ " + money(state.balance);
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
      document.getElementById("balance").textContent = "$ " + money(state.balance);
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


# --------------------------------------------------------------------------- #
# Рынок — мини-аппка
# --------------------------------------------------------------------------- #


def _lot_payload(lot: dict[str, Any], viewer_id: int) -> dict[str, Any]:
    """Лот для мини-аппки. decorate_lot НЕ кладёт карту в словарь — берём её
    из card_id сами, иначе все лоты выглядят кейсами."""
    from .handlers import decorate_lot

    decorated = decorate_lot(dict(lot))
    card_id = decorated.get("card_id")
    is_case = decorated.get("kind") == "case" or not card_id
    data: dict[str, Any] = {
        "id": int(decorated["id"]),
        "price": int(decorated["price"]),
        "seller": decorated.get("first_name") or decorated.get("username") or "игрок",
        "seller_id": int(decorated.get("seller_id") or 0),
        "rating": round(float(decorated.get("rating") or 5.0), 2),
        "mine": int(decorated.get("seller_id") or 0) == int(viewer_id),
        "case": is_case,
    }
    if not is_case:
        card = get_card(str(card_id))
        stats = decorated.get("stats") or {}
        data["card"] = {
            "name": card.display_name,
            "emoji": card.rarity_emoji,
            "rarity": card.rarity_title,
            "hp": stats.get("hp", card.hp),
            "atk": stats.get("atk", card.atk),
            "def": stats.get("def", 0),
        }
        image = image_url(card.card_id)
        if image:
            data["image"] = image
    return data


@router.get("/api/market")
async def api_market(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    user_id = int(user["id"])
    lots = await state.market.list_lots(24, 0)
    mine = await state.market.seller_lots(user_id, 24)
    rating = await state.market.rating_info(user_id)
    return JSONResponse(
        {
            "me": {
                "name": user.get("first_name") or "игрок",
                "balance": await state.market.balance(user_id),
                "rating": round(float(rating["rating"]), 2),
                "total": await state.market.count_lots(),
            },
            "lots": [_lot_payload(lot, user_id) for lot in lots],
            "mine": [_lot_payload(lot, user_id) for lot in mine],
        }
    )


@router.post("/api/market/buy")
async def api_market_buy(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
        body = await request.json()
        result = await state.market.buy_lot(
            int(body.get("lot_id", 0)), int(user["id"])
        )
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)
    except Exception as error:  # noqa: BLE001
        return JSONResponse({"error": str(error)}, status_code=400)
    return JSONResponse(
        {
            "ok": True,
            "price": int(result.get("price", 0)),
            "balance": await state.market.balance(int(user["id"])),
        }
    )


@router.post("/api/market/cancel")
async def api_market_cancel(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
        body = await request.json()
        await state.market.cancel_lot(int(body.get("lot_id", 0)), int(user["id"]))
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)
    except Exception as error:  # noqa: BLE001
        return JSONResponse({"error": str(error)}, status_code=400)
    return JSONResponse({"ok": True})


# --------------------------------------------------------------------------- #
# Биржа — API
# --------------------------------------------------------------------------- #


@router.get("/api/stocks")
async def api_stocks(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    repo = state.stocks
    # Курс двигает фоновый воркер; здесь только читаем текущее состояние.
    data = await repo.overview(int(user["id"]))
    data["me"]["name"] = user.get("first_name") or "игрок"
    # Живые данные: WebView не должен отдавать закешированный курс.
    return JSONResponse(data, headers={"Cache-Control": "no-store"})


async def _stock_trade(request: Request, kind: str) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
        body = await request.json()
        slug = str(body.get("slug", ""))
        shares = int(body.get("shares", 0))
        repo = state.stocks
        if kind == "buy":
            result = await repo.buy(int(user["id"]), slug, shares)
        else:
            result = await repo.sell(int(user["id"]), slug, shares)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)
    except StocksError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    except Exception:  # noqa: BLE001
        log.exception("Биржа: сделка не прошла")
        return JSONResponse({"error": "Не получилось, попробуй ещё"}, status_code=500)
    return JSONResponse({"ok": True, **result})


@router.post("/api/stocks/buy")
async def api_stocks_buy(request: Request) -> JSONResponse:
    return await _stock_trade(request, "buy")


@router.post("/api/stocks/sell")
async def api_stocks_sell(request: Request) -> JSONResponse:
    return await _stock_trade(request, "sell")


# --------------------------------------------------------------------------- #
# Кейсы и рулетка — мини-аппки. До «ОБНОВЛЕНИЯ» закрыты.
# --------------------------------------------------------------------------- #

LIVE_KEY = "miniapps_live"


async def _live(request: Request) -> bool:
    value = await request.app.state.db.get_setting(LIVE_KEY)
    return value == "1"


def _wheel_payload() -> list[dict]:
    segments = wheel_segments()
    total = sum(float(item["weight"]) for item in segments) or 1.0
    for item in segments:
        item["angle"] = round(float(item["weight"]) / total * 360.0, 2)
    return segments


def _reset_text() -> str:
    from datetime import datetime, timezone

    seconds = (
        next_roulette_reset() - datetime.now(timezone.utc)
    ).total_seconds()
    hours = int(max(0, seconds) // 3600)
    minutes = int(max(0, seconds) % 3600 // 60)
    return f"Сброс через {hours} ч {minutes} мин"


@router.get("/case_app", response_class=HTMLResponse)
async def case_app_page() -> HTMLResponse:
    return HTMLResponse(inject(CASE_PAGE))


@router.get("/roulette_app", response_class=HTMLResponse)
async def roulette_app_page() -> HTMLResponse:
    return HTMLResponse(inject(ROULETTE_PAGE))


async def _games_user(request: Request) -> tuple[int, JSONResponse | None]:
    try:
        user = await _player(request)
    except ShopError as error:
        return 0, JSONResponse({"error": str(error)}, status_code=401)
    if not await _live(request):
        return 0, JSONResponse(
            {"error": "Обновление ещё не вышло. Следи за анонсами!"},
            status_code=403,
        )
    return int(user["id"]), None


@router.get("/api/case")
async def api_case(request: Request) -> JSONResponse:
    state = request.app.state
    uid, error = await _games_user(request)
    if error is not None:
        return error
    cases = await state.db.user_cases(uid)
    next_d = bool(cases) and str(cases[0].get("source") or "") == cases_mod.CASE_D_SOURCE
    return JSONResponse(
        {
            "cases": len(cases),
            "count_g": sum(
                1 for c in cases if str(c.get("source") or "") != cases_mod.CASE_D_SOURCE
            ),
            "count_d": sum(
                1 for c in cases if str(c.get("source") or "") == cases_mod.CASE_D_SOURCE
            ),
            "pool": cases_mod.case_pool(),
            "pool_d": cases_mod.case_pool_d(),
            "next_d": next_d,
            "balance": await state.market.balance(uid),
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post("/api/case/open")
async def api_case_open(request: Request) -> JSONResponse:
    state = request.app.state
    uid, error = await _games_user(request)
    if error is not None:
        return error
    cases = await state.db.user_cases(uid)
    if not cases:
        return JSONResponse({"error": "Кейсов нет — крути рулетку"}, status_code=400)
    case = cases[0]
    is_d = str(case.get("source") or "") == cases_mod.CASE_D_SOURCE
    if not await state.db.open_case(uid, int(case["id"])):
        return JSONResponse({"error": "Этот кейс уже открыт"}, status_code=400)
    card = cases_mod.roll_case_d() if is_d else roll_case_card()
    counts = await state.db.get_collection(uid)
    is_new = card.card_id not in counts
    count = await state.db.add_card(uid, card.card_id)
    await state.db.add_points(uid, card.points)
    left = len(await state.db.user_cases(uid))
    return JSONResponse(
        {
            "ok": True,
            "card": {
                "id": card.card_id,
                "name": card.name,
                "emoji": card.rarity_emoji,
                "rarity": card.rarity,
                "rarity_title": rarity_name(card.rarity),
                "points": card.points,
                "color": cases_mod.RARITY_COLORS.get(card.rarity, "#334155"),
            },
            "cases": left,
            "is_new": is_new,
            "is_d": is_d,
            "count": count,
        }
    )


async def _points_balance(state, user_id: int) -> int:
    """Очки игрока: в проде через маркет, в тестах — прямо из базы."""
    market = getattr(state, "market", None)
    if market is not None:
        with contextlib.suppress(Exception):
            return int(await market.balance(user_id))
    return int(await state.db.player_points(user_id))


@router.get("/api/case/ultra")
async def api_case_ultra_state(request: Request) -> JSONResponse:
    """Что внутри кейса «Ультра» и сколько он стоит."""
    state = request.app.state
    uid, error = await _games_user(request)
    if error is not None:
        return error
    return JSONResponse(
        {
            "price": cases_mod.ULTRA_CASE_PRICE,
            "odds": cases_mod.ultra_case_odds(),
            "cards": [
                {
                    "id": card_id,
                    "name": CARDS_BY_ID[card_id].name,
                    "emoji": CARDS_BY_ID[card_id].rarity_emoji,
                }
                for card_id in cases_mod.ULTRA_CASE_IDS
                if card_id in CARDS_BY_ID
            ],
            "balance": await _points_balance(state, uid),
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post("/api/case/ultra")
async def api_case_ultra(request: Request) -> JSONResponse:
    """Купить и сразу открыть кейс «Ультра»."""
    state = request.app.state
    uid, error = await _games_user(request)
    if error is not None:
        return error
    price = cases_mod.ULTRA_CASE_PRICE
    if not await state.db.spend_points(uid, price):
        return JSONResponse(
            {"error": "Нужно " + str(price) + " очков"}, status_code=400
        )
    result = cases_mod.roll_ultra_case()
    payload: dict[str, Any] = {"ok": True, "kind": result["kind"], "price": price}
    if result["kind"] == "ultra":
        card = CARDS_BY_ID.get(result["card"])
        if card is not None:
            counts = await state.db.get_collection(uid)
            payload["is_new"] = card.card_id not in counts
            await state.db.add_card(uid, card.card_id)
            await state.db.add_points(uid, card.points)
            payload["card"] = {
                "id": card.card_id,
                "name": card.name,
                "emoji": card.rarity_emoji,
                "rarity": card.rarity,
                "rarity_title": rarity_name(card.rarity),
                "points": card.points,
                "color": cases_mod.RARITY_COLORS.get(card.rarity, "#334155"),
            }
    elif result["kind"] == "spin":
        await state.db.grant_spin_limit(uid, roulette_day_key(), 1, SPINS_PER_DAY)
    elif result["kind"] == "points":
        await state.db.add_points(uid, int(result["amount"]))
        payload["amount"] = int(result["amount"])
    payload["balance"] = await _points_balance(state, uid)
    return JSONResponse(payload)


@router.get("/api/roulette")
async def api_roulette(request: Request) -> JSONResponse:
    state = request.app.state
    uid, error = await _games_user(request)
    if error is not None:
        return error
    left = await state.db.roulette_left(uid, roulette_day_key(), SPINS_PER_DAY)
    return JSONResponse(
        {
            "segments": _wheel_payload(),
            "spins_left": left,
            "balance": await state.market.balance(uid),
            "reset_text": _reset_text(),
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post("/api/roulette/spin")
async def api_roulette_spin(request: Request) -> JSONResponse:
    state = request.app.state
    uid, error = await _games_user(request)
    if error is not None:
        return error
    left = await state.db.claim_roulette(uid, roulette_day_key(), SPINS_PER_DAY)
    if left is None:
        return JSONResponse({"error": "Спины на сегодня кончились"}, status_code=400)
    prize = roll_prize()
    kind, value = prize
    if kind == roulette_mod.PRIZE_POINTS:
        await state.db.add_points(uid, int(value))
        label = f"💰 +{int(value)} очков!"
    elif kind == roulette_mod.PRIZE_CASE:
        await state.db.add_case(uid, "roulette")
        label = "📦 Кейс! Открывай в кейсах."
    else:
        card = get_card(str(value))
        await state.db.add_card(uid, card.card_id)
        await state.db.add_points(uid, card.points)
        label = f"🃏 Главный приз — {card.name}!"
    return JSONResponse(
        {
            "ok": True,
            "index": segment_index(prize),
            "prize_label": label,
            "spins_left": left,
            "balance": await state.market.balance(uid),
        }
    )


@router.get("/market", response_class=HTMLResponse)
async def market_app() -> HTMLResponse:
    return HTMLResponse(inject(MARKET_PAGE))


@router.get("/stocks", response_class=HTMLResponse)
async def stocks_app() -> HTMLResponse:
    return HTMLResponse(inject(STOCKS_PAGE))


STOCKS_PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<title>Северо-Юг · Биржа</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&display=swap" rel="stylesheet">
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{
  --bg:#0e1116; --panel:#161b24; --panel2:#1d2430; --line:#252e3d; --line2:#1a2230;
  --ink:#f2ece5; --muted:#8b93a7;
  --acc:#dc8a3f; --acc2:#efaa5f; --acc-ink:#1b1206;
  --up:#9dc941; --down:#e0407a;
  --mono:'JetBrains Mono',ui-monospace,SFMono-Regular,monospace;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0;overscroll-behavior:none}
body{
  background:#0e1116!important;color:#f2ece5;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  min-height:100vh;padding-bottom:190px;
}
body::before{
  content:"";position:fixed;inset:0;z-index:0;pointer-events:none;
  background:radial-gradient(1100px 560px at 85% -12%,#1b2740 0%,#0e1116 58%);
}
/* встроенная тема рисует свою шапку — у биржи своя */
#__back{display:none!important}
.wrap{position:relative;z-index:1;max-width:560px;margin:0 auto}

/* ---------- шапка ---------- */
.top{
  position:sticky;top:0;z-index:9;display:flex;align-items:center;gap:10px;
  padding:14px 15px;background:#0e1116e6;backdrop-filter:blur(14px);
  border-bottom:1px solid var(--line2);
}
.back{
  display:inline-flex;align-items:center;gap:6px;text-decoration:none;
  background:#161b24!important;border:1px solid #252e3d!important;
  border-radius:999px;color:#f2ece5!important;padding:8px 14px;
  font:800 12px/1 inherit;
}
.ttl{flex:1;text-align:center;font:900 13px/1 inherit;letter-spacing:2.4px}
.live{display:inline-flex;align-items:center;gap:6px;color:var(--up);
  font:700 10px/1 var(--mono);letter-spacing:1.2px}
.live i{width:7px;height:7px;border-radius:50%;background:var(--up);
  box-shadow:0 0 9px var(--up);animation:pulse 1.8s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}

/* ---------- акция ---------- */
.hero{padding:18px 15px 4px}
.hero .nm{font-size:23px;font-weight:900;letter-spacing:-.5px;line-height:1.15}
.hero .sub{font-size:11.5px;color:var(--muted);margin-top:4px}
.hero .pr{
  margin-top:14px;font:900 42px/1 var(--mono);letter-spacing:-1.8px;
  font-variant-numeric:tabular-nums;
}
.ch{
  display:inline-flex;align-items:center;gap:6px;margin-top:9px;padding:6px 11px;
  border-radius:999px;font:800 12px/1 var(--mono);font-variant-numeric:tabular-nums;
}
.ch.up{color:var(--up)!important;background:#9dc9411f}
.ch.down{color:var(--down)!important;background:#e0407a1f}
.up{color:var(--up)!important}
.down{color:var(--down)!important}

/* ---------- плитки ---------- */
.stats{display:grid;grid-template-columns:1fr 1fr;gap:9px;padding:14px 15px 4px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:11px 13px}
.stat span{display:block;font-size:10px;letter-spacing:1.1px;text-transform:uppercase;
  color:var(--muted);font-weight:800}
.stat b{display:block;margin-top:5px;font:900 16px/1.15 var(--mono);
  font-variant-numeric:tabular-nums}

/* ---------- портфель ---------- */
.pf{
  margin:14px 15px 4px;padding:13px 14px;border-radius:16px;
  background:var(--panel);border:1px solid var(--line);
  position:relative;overflow:hidden;
}
.pf::before{
  content:"";position:absolute;left:0;top:12px;bottom:12px;width:3px;
  border-radius:0 3px 3px 0;background:var(--acc);
}
.pf .pt{padding-left:10px;font-size:10px;letter-spacing:1.4px;text-transform:uppercase;
  color:var(--muted);font-weight:800}
.pf .pr{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:11px;
  padding-left:10px}
.pf .pr>div{display:flex;flex-direction:column;gap:4px;min-width:0}
.pf .pr span{font-size:9.5px;letter-spacing:.8px;text-transform:uppercase;
  color:var(--muted);font-weight:800}
.pf .pr b{font:900 15px/1.15 var(--mono);font-variant-numeric:tabular-nums}
.pf .sub{padding-left:10px;margin-top:10px;font-size:11px;color:var(--muted);line-height:1.5}

/* ---------- график ---------- */
.chart{padding:14px 15px 0}
.chartbox{background:#12161d;border:1px solid #1e2634;border-radius:16px;
  overflow:hidden;position:relative}
.charthead{display:flex;justify-content:space-between;align-items:center;
  padding:11px 13px 2px;font-size:10px;letter-spacing:1.3px;color:var(--muted);
  font-weight:800}
#cv{height:240px;width:100%}
.note{padding:10px 15px 0;font-size:11.5px;color:var(--muted);line-height:1.5}

/* ---------- липкая панель сделки ---------- */
.dock{
  position:fixed;left:0;right:0;bottom:0;z-index:14;
  padding:10px 15px calc(12px + env(safe-area-inset-bottom));
  background:linear-gradient(#0e111600,#0e1116f7 40%);
  backdrop-filter:blur(16px);border-top:1px solid var(--line2);
}
.stepper{display:flex;gap:7px;margin-bottom:9px}
.stepper button{
  flex:1;border:1px solid #252e3d!important;background:#161b24!important;
  color:#8b93a7!important;border-radius:11px;padding:9px 0;font:800 11px/1 inherit;
}
.stepper button.on{
  background:#dc8a3f!important;color:#1b1206!important;border-color:#dc8a3f!important;
}
.act{display:flex;gap:9px}
.act button{flex:1 1 0;min-width:0;width:auto;margin:0;border:0;border-radius:14px;
  padding:16px;font:900 15px/1 inherit;letter-spacing:.3px}
.act .buy{background:linear-gradient(#efaa5f,#dc8a3f)!important;color:#1b1206!important;
  box-shadow:0 6px 18px #dc8a3f33!important}
.act .sell{background:#1d2430!important;color:#f2ece5!important;
  border:1px solid #2b3648!important;box-shadow:none!important}
.act button[disabled]{opacity:.4!important}

/* ---------- список акций ---------- */
.list{padding:16px 15px 0}
.lhead{font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted);
  font-weight:800;padding:0 2px 10px}
.row{
  display:flex;align-items:center;gap:12px;background:var(--panel);
  border:1px solid var(--line);border-radius:14px;padding:12px 13px;margin-bottom:8px;
  transition:border-color .15s ease,background .15s ease;
}
.row.on{border-color:var(--acc);background:#1b2130}
.row .av{width:38px;height:38px;border-radius:12px;border:1px solid var(--line);
  flex:0 0 auto;display:flex;align-items:center;justify-content:center;font-size:17px;
  background:var(--panel2)}
.row .mid{flex:1;min-width:0}
.row .nm{font-size:14px;font-weight:800;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis}
.row .mt{font-size:11px;color:var(--muted);margin-top:2px}
.row .rt{text-align:right}
.row .rt b{display:block;font:900 14px/1.1 var(--mono);font-variant-numeric:tabular-nums}
.row .rt i{display:block;margin-top:3px;font:800 11px/1 var(--mono);
  font-variant-numeric:tabular-nums}

/* ---------- тост ---------- */
#toast{
  position:fixed;left:14px;right:14px;bottom:190px;z-index:30;
  background:#1d2430;color:#f2ece5;border:1px solid #2b3648;border-radius:13px;
  padding:13px 15px;font-size:12.5px;line-height:1.45;
  transform:translateY(240%);transition:transform .25s ease;
}
#toast.on{transform:translateY(0)}
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <a class="back" href="/hub">← ХАБ</a>
    <div class="ttl">БИРЖА</div>
    <div class="live"><i></i>LIVE</div>
  </header>

  <section class="hero">
    <div class="nm" id="nm">…</div>
    <div class="sub" id="sub">акция · курс обновляется каждый час</div>
    <div class="pr" id="pr">…</div>
    <div class="ch" id="ch"></div>
  </section>

  <div class="stats">
    <div class="stat"><span>Покупка</span><b id="stBuy">…</b></div>
    <div class="stat"><span>Продажа</span><b id="stSell">…</b></div>
    <div class="stat"><span>У тебя акций</span><b id="stShares">…</b></div>
    <div class="stat"><span>Твоя прибыль</span><b id="stPnl">…</b></div>
  </div>

  <div class="pf" id="pf">
    <div class="pt">Портфель</div>
    <div class="pr">
      <div><span>Вложено</span><b id="pfSpent">…</b></div>
      <div><span>Сейчас</span><b id="pfValue">…</b></div>
      <div><span>Прибыль</span><b id="pfPnl">…</b></div>
    </div>
    <div class="sub" id="pfSub"></div>
  </div>

  <section class="chart">
    <div class="chartbox">
      <div class="charthead"><span>ГРАФИК</span><span>15 МИН · СВЕЧИ</span></div>
      <div id="cv"></div>
    </div>
    <div class="note" id="note"></div>
  </section>

  <div class="list">
    <div class="lhead">Все акции</div>
    <div id="rows"></div>
  </div>
</div>

<div class="dock">
  <div class="stepper" id="stepBar"></div>
  <div class="act">
    <button class="buy" id="buyBtn">Купить</button>
    <button class="sell" id="sellBtn">Продать</button>
  </div>
</div>

<div id="toast"></div>
<script>
const tg = window.Telegram ? window.Telegram.WebApp : null;
const headers = {"X-Telegram-Init-Data": tg ? tg.initData : "", "Content-Type": "application/json"};
// Таймфрейм в СЕКУНДАХ. История пишется раз в TICK секунд — свеча
// должна занимать ровно столько точек, сколько нужно по времени.
const TFS = [["1м", 60], ["5м", 300], ["15м", 900], ["1ч", 3600]];
const TICK = 15;
let S = {data: null, slug: null, tf: 0, shares: 1, busy: false};

function esc(s){ return String(s).replace(/[<>&]/g, c => ({"<":"&lt;",">":"&gt;","&":"&amp;"}[c])); }
function money(n){ return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, " "); }
function toast(t){
  const el = document.getElementById("toast");
  el.textContent = t; el.className = "on";
  clearTimeout(el._t); el._t = setTimeout(() => el.className = "", 3000);
}
function cur(){ return S.data.stocks.find(s => s.slug === S.slug); }

// Свечи: одна свеча = ровно столько точек истории, сколько нужно по времени.
// История пишется раз в TICK секунд, поэтому 1м = 4 точки, 5м = 20, 1ч = 240.
const CHART_MIN = 15;
const PER_CANDLE = 2;
function candles(history){
  // Если истории мало — режем по одному тику, чтобы свечей было больше.
  const per = PER_CANDLE;
  const need = Math.round(CHART_MIN * 60 / TICK / PER_CANDLE);
  let n = Math.min(need, Math.floor(history.length / per));
  // На 1ч истории может не хватить — тогда берём сколько есть,
  // но ось всё равно покажет настоящее время, а не выдуманное.

  if (n < 1) return {bars: [], stepSec: per * TICK};
  const start = history.length - n * per;
  const out = [];
  for (let k = 0; k < n; k++){
    const a = start + k * per;
    const chunk = history.slice(a, a + per);
    if (chunk.length < 1) continue;
    out.push({
      o: chunk[0], c: chunk[chunk.length - 1],
      h: Math.max.apply(null, chunk), l: Math.min.apply(null, chunk),
    });
  }
  return {bars: out, stepSec: per * TICK};
}
// Цвета свечей. В SVG-атрибутах var() не работает — только конкретный цвет.
const GREEN = "#9dc941", RED = "#e0407a";

let chart = null, series = null;
function draw(){
  const s = cur();
  if (!s) return;
  const res = candles(s.history);
  const bars = res.bars;
  if (!bars.length) return;
  const el = document.getElementById("cv");
  if (!el) return;
  el.style.height = "240px";
  if (typeof LightweightCharts === "undefined"){
    el.innerHTML = '<div style="padding:18px;font:12px JetBrains Mono,monospace;color:#e0407a">График не загрузился</div>';
    return;
  }
  if (!el) return;
  if (!chart){
    el.innerHTML = "";
    chart = LightweightCharts.createChart(el, {
      width: el.clientWidth || 320,
      height: 240,
      layout: {
        background: { type: "solid", color: "#12161d" },
        textColor: "#8b93a7",
        fontFamily: "'JetBrains Mono', ui-monospace, monospace",
        fontSize: 11,
      },
      grid: { vertLines: { color: "#1e2634" }, horzLines: { color: "#1e2634" } },
      rightPriceScale: { borderColor: "#1e2634", scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: {
        borderColor: "#1e2634", timeVisible: true, secondsVisible: false,
        rightOffset: 0,
      },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    });
    series = chart.addCandlestickSeries({
      upColor: "#9dc941", downColor: "#e0407a",
      borderUpColor: "#9dc941", borderDownColor: "#e0407a",
      wickUpColor: "#9dc941", wickDownColor: "#e0407a",
    });
    new ResizeObserver(function(){ if (chart) chart.applyOptions({ width: el.clientWidth }); }).observe(el);
  }
  const now = Math.floor(Date.now() / 1000);
  // Время честное: шаг = сколько секунд реально покрывает одна свеча.
  series.setData(bars.map(function(b, i){
    return {
      time: now - (bars.length - i) * res.stepSec,
      open: b.o, high: b.h, low: b.l, close: b.c,
    };
  }));
  // Все свечи влезают в экран: ширина / число свечей, листать нечего.
  chart.timeScale().fitContent();
}
function paintPortfolio(){
  const p = S.data.portfolio;
  const positions = S.data.stocks.filter(x => x.my_shares > 0);
  document.getElementById("pfSpent").textContent = money(p.spent);
  document.getElementById("pfValue").textContent = money(p.value);
  const pnl = document.getElementById("pfPnl");
  pnl.textContent = (p.pnl >= 0 ? "+" : "") + money(p.pnl);
  pnl.className = p.pnl >= 0 ? "up" : "down";
  document.getElementById("pfSub").textContent = positions.length
    ? "Позиций: " + positions.length + " · " +
      positions.map(x => x.name + " ×" + x.my_shares).join(", ")
    : "Акций нет — портфель пуст.";
}
function paint(){
  const s = cur();
  if (!s){ return; }
  paintPortfolio();
  const down = s.change < 0;
  document.getElementById("nm").textContent = s.name;
  document.getElementById("sub").textContent = "акция · " + (s.pump ? "идёт памп" : "торги идут");
  document.getElementById("pr").textContent = money(s.price);
  const ch = document.getElementById("ch");
  ch.textContent = (down ? "" : "+") + s.change + "% за сутки";
  ch.className = "ch " + (down ? "down" : "up");
  document.getElementById("stBuy").textContent = money(s.buy_price);
  document.getElementById("stSell").textContent = money(s.sell_price);
  document.getElementById("stShares").textContent = s.my_shares;
  const pnl = document.getElementById("stPnl");
  pnl.textContent = (s.my_pnl >= 0 ? "+" : "") + money(s.my_pnl);
  pnl.className = s.my_pnl >= 0 ? "up" : "down";
  document.getElementById("note").textContent = s.my_shares
    ? "Вложено " + money(s.my_spent) + " · сейчас стоит " + money(s.my_value) +
      " · свободно " + s.room + " акций"
    : "Акций нет. Свободно " + s.room + " мест.";
  document.getElementById("buyBtn").disabled = s.room < S.shares || S.busy;
  document.getElementById("sellBtn").disabled = s.my_shares < S.shares || S.busy;
  document.getElementById("rows").innerHTML = S.data.stocks.map(x => {
    const d = x.change < 0;
    return '<div class="row' + (x.slug === S.slug ? " on" : "") + '" data-slug="' + x.slug + '">' +
      '<div class="av">' + x.emoji + '</div>' +
      '<div class="mid"><div class="nm">' + esc(x.name) + '</div>' +
      '<div class="mt">у тебя ' + x.my_shares + ' · свободно ' + x.room + '</div></div>' +
      '<div class="rt"><b>' + money(x.price) + '</b>' +
      '<i class="' + (d ? "down" : "up") + '">' + (d ? "" : "+") + x.change + '%</i></div></div>';
  }).join("");
  document.querySelectorAll("[data-slug]").forEach(el => el.onclick = () => {
    S.slug = el.dataset.slug; S.shares = 1; paint(); draw(); renderStep();
  });
  draw();
}
function renderStep(){
  const presets = [1, 5, 10, 25];
  document.getElementById("stepBar").innerHTML = presets.map(n =>
    '<button class="' + (S.shares === n ? "on" : "") + '" data-n="' + n + '">' + n + ' акц.</button>').join("");
  document.querySelectorAll("[data-n]").forEach(b => b.onclick = () => {
    S.shares = +b.dataset.n; renderStep(); paint();
  });
}
async function trade(kind){
  if (S.busy) return;
  S.busy = true; paint();
  try{
    const r = await fetch("/api/stocks/" + kind, {method:"POST", headers,
      body: JSON.stringify({slug: S.slug, shares: S.shares})});
    const d = await r.json();
    if (d.error){ toast(d.error); }
    else {
      if (d.kind === "dep"){
        toast("Получено " + Number(d.dep).toFixed(5) + " деп-коинов по курсу " +
          Math.round(d.dep_rate).toLocaleString("ru") + " · всего " +
          Number(d.dep_balance).toFixed(5));
      } else {
        toast((kind === "buy" ? "Куплено " : "Продано ") + S.shares + " акц.");
      }
      if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
    }
  }catch(e){ toast("Связь потерялась"); }
  S.busy = false;
  await load(true);
}
async function load(keep){
  try{
    const r = await fetch("/api/stocks", {headers});
    const d = await r.json();
    if (d.error){ toast(d.error); return; }
    S.data = d;
    if (!keep || !S.slug) S.slug = d.stocks.length ? d.stocks[0].slug : null;
    paint();
  }catch(e){ toast("Не смог загрузить"); }
}
document.getElementById("buyBtn").onclick = () => trade("buy");
document.getElementById("sellBtn").onclick = () => trade("sell");
renderStep();
if(tg){ tg.ready(); tg.expand(); }
load(false);
setInterval(() => load(true), 20000);
</script>
</body>
</html>
"""


MARKET_PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Северо-Юг · Рынок</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{
  --bg:#f6f6f8; --card:#ffffff; --ink:#15161a; --muted:#6b7280; --line:#e6e7eb;
  --accent:#4f46e5; --accent-soft:#eef0fe; --ok:#0f9d58; --bad:#d93025;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0}
body{
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg);color:var(--ink);min-height:100vh;padding-bottom:100px;
}
header{
  position:sticky;top:0;z-index:5;background:color-mix(in srgb, var(--bg) 92%, transparent);
  backdrop-filter:saturate(180%) blur(12px);border-bottom:1px solid var(--line);
  padding:14px 18px 12px
}
.hrow{display:flex;align-items:baseline;justify-content:space-between;gap:12px}
h1{margin:0;font-size:19px;letter-spacing:-.2px}
.sub{font-size:12px;color:var(--muted);margin-top:3px}
.wallet{
  font-weight:700;font-size:15px;background:var(--accent-soft);color:var(--accent);
  border-radius:999px;padding:7px 14px;white-space:nowrap
}
.tabs{display:flex;gap:6px;padding:12px 18px 4px}
.tab{
  border:1px solid var(--line);background:var(--panel);color:var(--muted);border-radius:10px;
  padding:9px 14px;font-size:14px;font-weight:600;transition:.15s
}
.tab.on{background:var(--accent);color:#fff;border-color:var(--accent)}
main{padding:12px 18px}
.lot{
  background:var(--card);border:1px solid var(--line);border-radius:16px;
  overflow:hidden;margin-bottom:12px;box-shadow:0 1px 2px rgba(16,24,40,.04)
}
.lot .top{display:flex;gap:12px;padding:12px}
.art{
  width:74px;height:74px;border-radius:12px;object-fit:cover;background:var(--bg);
  flex:0 0 auto
}
.noart{
  width:74px;height:74px;border-radius:12px;background:var(--bg);flex:0 0 auto;
  display:flex;align-items:center;justify-content:center;font-size:26px
}
.info{flex:1;min-width:0}
.name{font-weight:700;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rar{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-top:2px}
.stats{display:flex;gap:12px;margin-top:7px;font-size:13px;font-weight:600;color:var(--ink)}
.seller{font-size:12px;color:var(--muted);margin-top:6px}
.bottom{
  display:flex;align-items:center;justify-content:space-between;gap:10px;
  padding:11px 12px;border-top:1px solid var(--line);background:var(--panel2)
}
.price{font-weight:800;font-size:17px;color:var(--acc2)}
.btn{
  border:0;border-radius:11px;padding:11px 18px;font-size:14px;font-weight:700;
  color:#fff;background:var(--accent);transition:.15s
}
.btn:active{transform:scale(.98)}
.btn.ghost{background:transparent;color:var(--bad);border:1px solid var(--line)}
.btn[disabled]{background:var(--panel2);color:var(--muted)}
.empty{text-align:center;color:var(--muted);padding:56px 20px;font-size:14px;line-height:1.6}
#toast{
  position:fixed;left:14px;right:14px;bottom:18px;background:var(--ink);color:#fff;
  border-radius:12px;padding:14px 16px;font-size:14px;line-height:1.45;
  transform:translateY(140%);transition:.26s cubic-bezier(.2,.8,.3,1);z-index:9
}
#toast.on{transform:translateY(0)}
#toast.ok{background:var(--ok)}
#toast.bad{background:var(--bad)}
</style>
</head>
<body>
<header>
  <div class="hrow">
    <div>
      <h1>Рынок</h1>
      <div class="sub" id="sub">лоты игроков</div>
    </div>
    <div class="wallet" id="balance">…</div>
  </div>
</header>
<div class="tabs" id="tabs"></div>
<main id="list"><div class="empty">Загружаю лоты…</div></main>
<div id="toast"></div>
<script>
const tg = window.Telegram ? window.Telegram.WebApp : null;
const headers = {"X-Telegram-Init-Data": tg ? tg.initData : "", "Content-Type":"application/json"};
let state = {lots: [], mine: [], tab: "all", balance: 0};

function money(n){ return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, " "); }
function toast(text, kind){
  const el = document.getElementById("toast");
  el.textContent = text; el.className = "on " + (kind || "");
  clearTimeout(el._t); el._t = setTimeout(() => el.className = "", 3200);
}
function esc(s){ return String(s).replace(/[<>&]/g, c => ({"<":"&lt;",">":"&gt;","&":"&amp;"}[c])); }

function renderTabs(){
  const tabs = [["all","Все лоты"],["mine","Мои лоты"]];
  document.getElementById("tabs").innerHTML = tabs.map(([k,t]) =>
    '<button class="tab'+(state.tab===k?' on':'')+'" data-tab="'+k+'">'+t+'</button>').join("");
  document.querySelectorAll(".tab").forEach(b => b.onclick = () => {
    state.tab = b.dataset.tab; renderTabs(); renderList();
  });
}
function lotHtml(lot){
  const c = lot.card;
  const art = lot.image
    ? '<img class="art" src="'+lot.image+'" alt="">'
    : '<div class="noart">'+(c ? c.emoji : "📦")+'</div>';
  const stats = c ? '<div class="stats"><span>❤️ '+c.hp+'</span><span>⚔️ '+c.atk+
    '</span><span>🛡 '+c.def+'%</span></div>' : '<div class="stats"><span>📦 кейс</span></div>';
  const name = c ? esc(c.name) : "Кейс";
  const rar = c ? c.emoji + " " + esc(c.rarity) : "закрытый кейс";
  const action = lot.mine
    ? '<button class="btn ghost" data-cancel="'+lot.id+'">Снять</button>'
    : '<button class="btn" data-buy="'+lot.id+'"'+(state.balance>=lot.price?"":" disabled")+'>'+
      (state.balance>=lot.price?"Купить":"Не хватает")+'</button>';
  return '<div class="lot"><div class="top">'+art+
    '<div class="info"><div class="name">'+name+'</div>'+
    '<div class="rar">'+rar+'</div>'+stats+
    '<div class="seller">Продавец: '+esc(lot.seller)+' · ⭐ '+lot.rating+
    (lot.mine?' · это твой лот':'')+'</div></div></div>'+
    '<div class="bottom"><div class="price">'+money(lot.price)+'</div>'+action+'</div></div>';
}
function renderList(){
  const items = state.tab === "all" ? state.lots : state.mine;
  document.getElementById("list").innerHTML = items.length
    ? items.map(lotHtml).join("")
    : '<div class="empty">'+(state.tab==="all" ? "Лотов пока нет.<br>Выстави свой: /sell #id цена" : "У тебя нет лотов.<br>Выставить: /sell #id цена")+'</div>';
  document.querySelectorAll("[data-buy]").forEach(b => b.onclick = () => act("buy", b.dataset.buy, b));
  document.querySelectorAll("[data-cancel]").forEach(b => b.onclick = () => act("cancel", b.dataset.cancel, b));
}
async function load(){
  try{
    const r = await fetch("/api/market", {headers});
    const d = await r.json();
    if(d.error){ toast(d.error, "bad"); return; }
    state.lots = d.lots; state.mine = d.mine; state.balance = d.me.balance;
    document.getElementById("balance").textContent = "$ " + money(state.balance);
    document.getElementById("sub").textContent = "лотов: " + d.me.total + " · репутация " + d.me.rating;
    renderTabs(); renderList();
  }catch(e){ toast("Не смог загрузить рынок", "bad"); }
}
async function act(kind, id, btn){
  btn.disabled = true; btn.textContent = "…";
  try{
    const r = await fetch("/api/market/"+kind, {method:"POST", headers, body: JSON.stringify({lot_id: Number(id)})});
    const d = await r.json();
    if(d.error) toast(d.error, "bad");
    else { toast(kind==="buy" ? "Покупка прошла!" : "Лот снят", "ok"); if(tg&&tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success"); }
  }catch(e){ toast("Связь потерялась", "bad"); }
  await load();
}
if(tg){ tg.ready(); tg.expand(); }
load();
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# Апгрейдер карт — мини-аппка
# --------------------------------------------------------------------------- #


@router.get("/api/upgrader")
async def api_upgrader(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    user_id = int(user["id"])
    counts = await state.db.get_collection(user_id)
    mine = [
        upgrader.card_payload(get_card(card_id), counts[card_id])
        for card_id in counts
        if card_id in CARDS_BY_ID
    ]
    mine.sort(key=lambda item: (-item["points"], item["name"]))
    targets = [
        upgrader.card_payload(card)
        for card in CARDS
        if card.card_id not in UPGRADER_EXCLUDED_CARD_IDS
    ]
    targets.sort(key=lambda item: (-item["points"], item["name"]))
    return JSONResponse(
        {
            "me": {
                "name": user.get("first_name") or "игрок",
                "balance": await state.market.balance(user_id),
            },
            "mine": mine,
            "targets": targets,
            "ladder": list(upgrader.LADDER),
            "steps": {str(key): value for key, value in upgrader.STEP_CHANCE.items()},
            "dep": {
                "balance": await state.db.dep_balance(user_id),
                "rate": await state.db.dep_rate(),
                "price": depcoins.BOOST_PRICE,
                "max": depcoins.MAX_BOOSTS,
                "step": depcoins.BOOST_STEP,
                "streak": await state.db.drift_state(user_id),
                "need": depcoins.DRIFT_NEEDED,
                "card": depcoins.DRIFT_CARD_ID,
            },
        }
    )


@router.post("/api/upgrader/spin")
async def api_upgrader_spin(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    try:
        body = await request.json()
        from_id = str(body.get("from", ""))
        to_id = str(body.get("to", ""))
        if from_id not in CARDS_BY_ID or to_id not in CARDS_BY_ID:
            raise ValueError("Такой карты нет.")
        if from_id == to_id:
            raise ValueError("Поставь и выбери разные карты.")

        source = get_card(from_id)
        target = get_card(to_id)

        boost = int(body.get("boost", 0) or 0)
        boost = max(0, min(depcoins.MAX_BOOSTS, boost))
        base_odd = upgrader.chance(source, target)
        odd = min(0.95, base_odd * depcoins.boost_multiplier(boost))
        won = upgrader.roll_odd(odd)

        user_id = int(user["id"])
        outcome = await state.db.run_upgrade(
            user_id, from_id, to_id, odd, won, boost=boost
        )
        if not outcome.get("ok"):
            raise ValueError(outcome.get("error", "Этой карты у тебя уже нет."))
    except Exception as error:  # noqa: BLE001
        return JSONResponse({"error": str(error)}, status_code=400)

    return JSONResponse(
        {
            "ok": True,
            "won": won,
            "chance": odd,
            "from": upgrader.card_payload(source),
            "to": upgrader.card_payload(target),
            "balance": await state.market.balance(user_id),
            "boost": boost,
            "base_chance": base_odd,
            "drift": bool(outcome.get("drift")),
            "drift_streak": int(outcome.get("streak") or 0),
            "dep": await state.db.dep_balance(user_id),
        }
    )


@router.get("/upgrader", response_class=HTMLResponse)
async def upgrader_app() -> HTMLResponse:
    return HTMLResponse(inject(UPGRADER_PAGE))






UPGRADER_PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<title>Северо-Юг · Апгрейдер</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{
  --bg:#0a0c11; --panel:#141822; --panel2:#1b2130; --line:#242c3d;
  --ink:#eef2f8; --muted:#7b8698; --acc:#f59e0b; --acc2:#ffc53d;
  --ok:#22c55e; --bad:#e5484d;
  --rare:#6b7280; --superrare:#3b82f6; --epic:#a855f7; --mythic:#ef4444;
  --legendary:#eab308; --secret:#64748b; --ultra:#e879f9; --teacher:#c2410c;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0;overscroll-behavior:none}
body{
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg);color:var(--ink);min-height:100vh;
  background-image:radial-gradient(80% 40% at 50% 0%,rgba(229,72,77,.14),transparent 65%)
}
.top{display:flex;align-items:center;justify-content:space-between;
  padding:12px 16px;border-bottom:1px solid var(--line);position:sticky;top:0;
  background:rgba(10,12,17,.9);backdrop-filter:blur(12px);z-index:8}
.logo{font-weight:900;letter-spacing:1.5px;font-size:15px}
.logo b{color:var(--bad)}
.bal{font-weight:800;font-size:13.5px;color:var(--acc2)}

.wrap{max-width:520px;margin:0 auto;padding:14px 14px 130px}

.slots{display:grid;grid-template-columns:1fr 26px 1fr;align-items:center;gap:6px}
.box{background:var(--panel);border:1px solid var(--line);border-radius:15px;padding:10px;text-align:center;min-height:118px;
  display:flex;flex-direction:column;align-items:center;justify-content:center;gap:5px}
.box.filled{border-color:var(--acc)}
.box img{width:70px;height:70px;object-fit:cover;border-radius:11px}
.box .ic{font-size:40px}
.box .nm{font-size:12px;font-weight:700;line-height:1.2}
.box .rr{font-size:9.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.7px}
.box .ph{font-size:11.5px;color:var(--muted);line-height:1.5}
.box .pr{font-size:11px;font-weight:800;color:var(--acc2)}
.arrow{text-align:center;color:var(--acc);font-size:18px;font-weight:900}

.stage{margin:18px 0 2px;position:relative;display:flex;align-items:center;justify-content:center;
  --up:#3fae6a;--down:#d8434a}
.drum{position:relative;width:400px;height:400px;max-width:86vw;max-height:86vw}
/* Стрелка неподвижна: она вне вращающегося циферблата */
.needle{position:absolute;top:-6px;left:50%;transform:translateX(-50%);z-index:6;
  width:0;height:0;border-left:13px solid transparent;border-right:13px solid transparent;
  border-top:24px solid var(--acc2);filter:drop-shadow(0 3px 9px rgba(0,0,0,.7))}
.needle::after{content:"";position:absolute;top:-9px;left:-6px;width:12px;height:12px;
  border-radius:50%;background:var(--acc2);box-shadow:0 0 12px var(--acc2)}
.dial{position:absolute;inset:0;width:100%;height:100%;
  transition:transform 6.2s cubic-bezier(.06,.68,.03,1)}
.dial circle{fill:none;stroke-linecap:butt;transition:stroke-dasharray .35s ease}
.trk{stroke:rgba(255,255,255,.05);stroke-width:46}
.zone-red{stroke:var(--down);stroke-width:28}
.zone-win{stroke:var(--up);stroke-width:28}
body .hub{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
  width:48%;height:48%;border:0!important;border-radius:50%!important;
  background:radial-gradient(circle at 50% 28%,var(--panel2),var(--panel))!important;
  color:var(--ink)!important;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.09),0 10px 30px rgba(0,0,0,.45)!important;
  display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1px;z-index:4}
body .hub:active{transform:translate(-50%,-50%) scale(.97)!important}
body .hub[disabled]{color:var(--muted)!important;opacity:.7}
.hub .v{font-size:30px;font-weight:900;letter-spacing:-1.2px;line-height:1}
.hub .ic{font-size:19px;font-weight:900;color:var(--acc);line-height:1;margin-top:3px}
.hub .tt{font-size:12px;font-weight:900;letter-spacing:2.4px}

.boost{display:flex;gap:9px;align-items:center;margin:13px 0 2px}
.boost button{flex:1;border:1px solid var(--line)!important;background:transparent!important;
  color:var(--ink)!important;border-radius:12px!important;padding:13px!important;
  font-size:13px!important;font-weight:800!important;box-shadow:none!important}
.boost button.on{background:var(--acc)!important;color:var(--acc-ink)!important;
  border-color:transparent!important}
.boost .dep{font-size:11.5px;color:var(--muted);min-width:92px;text-align:right;line-height:1.5}

.go{position:fixed;left:14px;right:14px;bottom:16px;max-width:492px;margin:0 auto;
  border:0;border-radius:15px;padding:17px;font-size:16px;font-weight:900;letter-spacing:.5px;
  color:#1a1204;background:linear-gradient(135deg,var(--acc2),var(--acc));
  box-shadow:0 10px 26px rgba(245,158,11,.3);z-index:9}
.go[disabled]{background:#1d2431;color:#5b6577;box-shadow:none}

.tabs{display:flex;gap:8px;margin:16px 0 10px}
.tab{flex:1;border:1px solid var(--line);background:var(--panel);color:var(--muted);
  border-radius:12px;padding:11px;font-size:13.5px;font-weight:700}
.tab.on{background:var(--acc);color:#1a1204;border-color:var(--acc)}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}
.card{position:relative;background:var(--panel);border:1.5px solid var(--line);border-radius:12px;
  padding:7px;text-align:center}
.card:active{transform:scale(.97)}
.card.on{border-color:var(--acc);background:var(--panel2)}
.card img{width:100%;height:56px;object-fit:cover;border-radius:8px;display:block}
.card .ic{font-size:30px;line-height:56px}
.card .nm{font-size:10.5px;font-weight:700;margin-top:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.card .pr{font-size:9.5px;color:var(--acc2);font-weight:700;margin-top:1px}
.card .ct{position:absolute;z-index:5;top:4px;right:5px;font-size:10px;
  font-weight:800;color:#fff;background:rgba(8,10,14,.94);
  border:1px solid rgba(255,255,255,.28);border-radius:7px;padding:1px 6px;
  box-shadow:0 2px 7px rgba(0,0,0,.55);line-height:15px}
.r-rare{border-color:rgba(107,114,128,.55)} .r-superrare{border-color:rgba(59,130,246,.7)}
.r-epic{border-color:rgba(168,85,247,.75)} .r-mythic{border-color:rgba(239,68,68,.75)}
.r-legendary{border-color:rgba(234,179,8,.8)} .r-secret{border-color:rgba(100,116,139,.85)}
.r-ultra{border-color:rgba(232,121,249,.9)} .r-teacher{border-color:rgba(194,65,12,.9)}
.empty{color:var(--muted);font-size:12.5px;line-height:1.6;text-align:center;padding:22px 8px;
  grid-column:1/-1}

.result{position:fixed;inset:0;background:rgba(8,10,14,.96);display:none;
  align-items:center;justify-content:center;flex-direction:column;gap:12px;z-index:20;padding:26px;text-align:center}
.result.on{display:flex}
.result .big{font-size:54px}
.result img{width:132px;height:132px;object-fit:cover;border-radius:16px;border:2px solid var(--acc)}
.result .ttl{font-size:22px;font-weight:900}
.result .txt{font-size:13.5px;color:var(--muted);line-height:1.6;max-width:400px}
.result .close{border:0;margin-top:8px;background:linear-gradient(135deg,var(--acc2),var(--acc));
  color:#1a1204;border-radius:13px;padding:14px 34px;font-size:15px;font-weight:800}
#toast{position:fixed;left:14px;right:14px;bottom:92px;background:#232a39;color:#fff;
  border-radius:11px;padding:13px 15px;font-size:13px;transform:translateY(200%);
  transition:.25s;z-index:30}
#toast.on{transform:translateY(0)}
#toast.bad{background:var(--bad)}
</style>
</head>
<body>
<div class="top">
  <div class="logo">UP<b>GRADER</b></div>
  <div class="bal" id="bal">…</div>
</div>

<div class="wrap">
  <div class="slots">
    <div class="box" id="slotA"><div class="ph">Твоя карта<br>выбери ниже</div></div>
    <div class="arrow">→</div>
    <div class="box" id="slotB"><div class="ph">Что хочешь<br>выбери ниже</div></div>
  </div>

  <div class="stage">
    <div class="drum">
      <div class="needle"></div>
      <svg class="dial" id="dial" viewBox="0 0 200 200">
        <g transform="rotate(-90 100 100)">
          <circle class="trk" cx="100" cy="100" r="80" pathLength="360"/>
          <circle class="zone-red" id="arcRed" cx="100" cy="100" r="80" pathLength="360"
                  stroke-dasharray="360 360"/>
          <circle class="zone-win" id="arcWin" cx="100" cy="100" r="80" pathLength="360"
                  stroke-dasharray="0 360"/>
        </g>
      </svg>
      <button class="hub" id="go" disabled>
        <span class="v" id="pct">—</span>
        <span class="ic">⌃</span>
        <span class="tt">АПГРЕЙД</span>
        <span id="word" style="display:none"></span>
      </button>
    </div>
  </div>

  <div class="boost" id="boostBox"></div>

  <div class="tabs">
    <button class="tab on" data-tab="mine" id="tabMine">Мои карты</button>
    <button class="tab" data-tab="targets" id="tabTargets">Вы получите</button>
  </div>
  <div class="cards" id="grid"></div>
</div>



<div class="result" id="result">
  <div class="big" id="rIcon">🎉</div>
  <div id="rArt"></div>
  <div class="ttl" id="rTitle"></div>
  <div class="txt" id="rText"></div>
  <button class="close" id="rClose">Забрать</button>
</div>

<div id="toast"></div>

<script>
const tg = window.Telegram ? window.Telegram.WebApp : null;
const headers = {"X-Telegram-Init-Data": tg ? tg.initData : "", "Content-Type": "application/json"};
const SEGMENTS = 40;
let S = {mine: [], targets: [], ladder: [], steps: {}, A: null, B: null, tab: "mine", busy: false,
  rotation: 0, boost: 0};
function shownChance(){
  if (!(S.A && S.B)) return 0;
  const step = (S.data && S.data.dep) ? S.data.dep.step : 1;
  return Math.min(0.95, chanceOf(S.A, S.B) * Math.pow(step, S.boost || 0));
}
function renderBoost(){
  const d = (S.data && S.data.dep) || {balance: 0, price: 5, max: 2, step: 1.35, streak: 0, need: 3};
  const b = S.boost || 0;
  const canUp = b < (d.max || 2) && (d.balance || 0) >= (d.price || 5);
  const box = document.getElementById("boostBox");
  box.innerHTML =
    '<button id="boostBtn" class="' + (b ? "on" : "") + '"' + ((canUp || b) ? "" : " disabled") + '>' +
      (b ? "Улучшено ×" + b : "Улучшить шанс") + ' · ' + (d.price || 5) + ' деп</button>' +
    '<div class="dep">' + (d.balance || 0).toFixed(5) + ' деп' +
      ((d.streak || 0) > 0 ? "<br>дрифт " + d.streak + "/" + (d.need || 3) : "") + '</div>';
  document.getElementById("boostBtn").onclick = () => {
    if (S.boost >= (d.max || 2)) S.boost = 0;
    else if ((d.balance || 0) < (d.price || 5) && !S.boost) { toast("Не хватает деп-коинов"); return; }
    else S.boost = (S.boost || 0) + 1;
    renderBoost(); paintDial(shownChance());
  };
}

function esc(s){ return String(s).replace(/[<>&]/g, c => ({"<":"&lt;",">":"&gt;","&":"&amp;"}[c])); }
function money(n){ return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, " "); }
function toast(t, bad){
  const el = document.getElementById("toast");
  el.textContent = t; el.className = "on" + (bad ? " bad" : "");
  clearTimeout(el._t); el._t = setTimeout(() => el.className = "", 3200);
}
function chanceOf(a, b){
  const d = S.ladder.indexOf(b.rarity_key) - S.ladder.indexOf(a.rarity_key);
  if (d in S.steps) return S.steps[d];
  return d > 7 ? 0.0002 : 0.95;
}
function pct(v){
  const p = v * 100;
  if (p >= 10) return p.toFixed(0) + "%";
  if (p >= 1) return p.toFixed(1) + "%";
  if (p >= 0.1) return p.toFixed(2) + "%";
  return p.toFixed(3) + "%";
}
function words(v){
  if (v >= 0.6) return "Очень высокий шанс";
  if (v >= 0.3) return "Высокий шанс";
  if (v >= 0.12) return "Средний шанс";
  if (v >= 0.04) return "Низкий шанс";
  if (v >= 0.005) return "Очень низкий шанс";
  return "Почти нереально";
}
// Циферблат: зелёная зона = шанс, красная = остальное.
// Зелёная рисуется от верхней точки по часовой стрелке.
function paintDial(chance){
  const valid = typeof chance === "number" && chance > 0;
  const g = valid ? Math.min(360, Math.max(1.5, chance * 360)) : 0;
  document.getElementById("arcWin").setAttribute("stroke-dasharray", g + " 360");
  const red = document.getElementById("arcRed");
  red.setAttribute("stroke-dasharray", (360 - g) + " 360");
  red.setAttribute("stroke-dashoffset", -g);
  document.getElementById("pct").textContent = valid ? pct(chance) : "—";
}
function cardEl(card, side){
  const on = side === "A" ? (S.A && S.A.id === card.id) : (S.B && S.B.id === card.id);
  const art = card.image ? '<img src="' + card.image + '" alt="">' : '<div class="ic">' + card.emoji + '</div>';
  const cnt = side === "A" ? '<div class="ct">×' + (card.count || 1) + '</div>' : '';
  return '<div class="card r-' + card.rarity_key + (on ? " on" : "") +
    '" data-side="' + side + '" data-id="' + card.id + '">' + cnt + art +
    '<div class="nm">' + esc(card.name) + '</div><div class="pr">' + money(card.price) + '</div></div>';
}
function box(card, which){
  if (!card) return '<div class="ph">' + which + '<br>выбери ниже</div>';
  const art = card.image ? '<img src="' + card.image + '" alt="">' : '<div class="ic">' + card.emoji + '</div>';
  return art + '<div class="nm">' + esc(card.name) + '</div><div class="rr">' + esc(card.rarity) +
    '</div><div class="pr">' + money(card.price) + '</div>';
}
function render(){
  const a = document.getElementById("slotA"), b = document.getElementById("slotB");
  a.innerHTML = box(S.A, "Твоя карта"); b.innerHTML = box(S.B, "Что хочешь");
  a.className = "box" + (S.A ? " filled" : ""); b.className = "box" + (S.B ? " filled" : "");

  const odd = S.A && S.B ? chanceOf(S.A, S.B) : null;
  document.getElementById("pct").textContent = odd === null ? "—" : pct(odd);
  document.getElementById("word").textContent = odd === null ? "выбери карты" : words(odd);

  const list = S.tab === "mine" ? S.mine : S.targets;
  const side = S.tab === "mine" ? "A" : "B";
  document.getElementById("grid").innerHTML = list.length
    ? list.map(c => cardEl(c, side)).join("")
    : '<div class="empty">' + (S.tab === "mine"
        ? "Пусто. Выбей карту командой «Северо-Юг»."
        : "Нет карт.") + '</div>';

  document.getElementById("tabMine").textContent = "Мои карты (" + S.mine.length + ")";
  document.getElementById("tabTargets").textContent = "Вы получите";
  document.getElementById("tabMine").className = "tab" + (S.tab === "mine" ? " on" : "");
  document.getElementById("tabTargets").className = "tab" + (S.tab === "targets" ? " on" : "");
  document.getElementById("go").disabled = !(S.A && S.B) || S.busy;

  document.querySelectorAll("[data-tab]").forEach(b2 => b2.onclick = () => { S.tab = b2.dataset.tab; render(); });
  document.querySelectorAll("[data-side]").forEach(el => {
    el.onclick = () => {
      const sd = el.dataset.side, id = el.dataset.id;
      if (sd === "A") S.A = S.mine.find(c => c.id === id) || null;
      else S.B = S.targets.find(c => c.id === id) || null;
      render();
      paintDial(shownChance()); renderBoost();
      if (S.tab === "mine" && S.A) { S.tab = "targets"; render(); }
    };
  });
}

async function load(){
  try{
    const r = await fetch("/api/upgrader", {headers});
    const d = await r.json();
    if (d.error){ toast(d.error, true); return; }
    S.mine = d.mine; S.targets = d.targets; S.ladder = d.ladder; S.steps = d.steps;
    document.getElementById("bal").textContent = "$ " + money(d.me.balance);
    if (S.A && !S.mine.some(c => c.id === S.A.id)) S.A = null;
    if (S.B && !S.targets.some(c => c.id === S.B.id)) S.B = null;
    if (!S.A && S.mine.length) S.A = S.mine[0];
    render();
    paintDial(shownChance()); renderBoost();
  }catch(e){ toast("Не смог загрузить", true); }
}
async function spin(){
  if (S.busy || !S.A || !S.B) return;
  S.busy = true; render();
  const odd = chanceOf(S.A, S.B);
  try{
    const r = await fetch("/api/upgrader/spin", {method:"POST", headers,
      body: JSON.stringify({from: S.A.id, to: S.B.id, boost: S.boost || 0})});
    const d = await r.json();
    if (d.error){ toast(d.error, true); S.busy = false; await load(); return; }

    // Крутим строго под результат. Зелёная зона идёт от верхней точки,
    // поэтому остановка на 360-x кладёт под стрелку точку x.
    paintDial(d.chance);
    const g = Math.max(1.5, d.chance * 360);
    let stop;
    if (d.won){
      stop = 360 - g * (0.15 + Math.random() * 0.7);
    } else {
      stop = 360 - (g + (360 - g) * (0.15 + Math.random() * 0.7));
    }
    const need = ((stop - (S.rotation % 360)) + 360) % 360;
    S.rotation += 360 * (5 + Math.floor(Math.random() * 3)) + need;
    document.getElementById("dial").style.transform = "rotate(" + S.rotation + "deg)";
    if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("medium");

    await new Promise(res => setTimeout(res, 6400));
    document.getElementById("rIcon").textContent = d.won ? "🎉" : "💀";
    document.getElementById("rArt").innerHTML = d.won && d.to.image
      ? '<img src="' + d.to.image + '" alt="">' : "";
    document.getElementById("rTitle").textContent = d.won ? esc(d.to.name) + " — твоя!" : "Не повезло";
    let tail = d.won
      ? d.from.name + " стал " + d.to.name + ". Шанс был " + pct(d.chance) + "."
      : d.from.name + " сгорел. Шанс был " + pct(d.chance) + ".";
    if (d.boost) tail += " Улучшение ×" + d.boost + " (было " + pct(d.base_chance) + ").";
    if (d.drift) tail += " Дрифт-комбо! Эльвира приехала в коллекцию.";
    else if (d.drift_streak) tail += " Дрифт " + d.drift_streak + "/3.";
    document.getElementById("rText").textContent = tail;
    document.getElementById("result").classList.add("on");
    if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred(d.won ? "success" : "error");
  }catch(e){ toast("Связь потерялась", true); }
  S.busy = false;
}
document.getElementById("go").onclick = spin;
document.getElementById("rClose").onclick = async () => {
  document.getElementById("result").classList.remove("on");
  S.A = null; S.B = null; S.tab = "mine";
  await load();
};
if(tg){ tg.ready(); tg.expand(); }
load();
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# Скупщик — мини-аппка
# --------------------------------------------------------------------------- #


async def _buyer_items(state, user_id: int) -> tuple[list[dict[str, Any]], int, int]:
    """Все карты игрока с ценой скупщика + итог по лишним копиям."""
    items: list[dict[str, Any]] = []
    dup_count = 0
    dup_total = 0

    counts = await state.db.get_collection(user_id)
    for card_id, count in counts.items():
        if card_id not in CARDS_BY_ID:
            continue
        card = get_card(card_id)
        payload = buyer.card_payload(card, count)
        payload.update(ref=f"card:{card_id}", kind="card", key=f"c{card_id}")
        items.append(payload)
        if count > 1:
            extra = count - 1
            dup_count += extra
            dup_total += buyer.price(card) * extra

    for row in await state.market.user_inventory(user_id):
        card = get_card(row["card_id"])
        payload = buyer.card_payload(card, 1, row["bonus"])
        payload.update(ref=f"inv:{row['id']}", kind="inv", key=f"i{row['id']}")
        items.append(payload)

    items.sort(key=lambda item: -item["price"])
    return items, dup_count, dup_total


@router.get("/api/buyer")
async def api_buyer(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    user_id = int(user["id"])
    items, dup_count, dup_total = await _buyer_items(state, user_id)
    return JSONResponse(
        {
            "me": {
                "name": user.get("first_name") or "игрок",
                "balance": await state.market.balance(user_id),
            },
            "rate": int(buyer.BUYER_RATE * 100),
            "items": items,
            "dupes": {"count": dup_count, "total": dup_total},
        }
    )


@router.post("/api/buyer/sell")
async def api_buyer_sell(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    user_id = int(user["id"])
    try:
        body = await request.json()
        ref = str(body.get("ref", ""))
        kind, _, value = ref.partition(":")
        if kind == "card":
            if value not in CARDS_BY_ID:
                raise ValueError("Такой карты нет.")
            card = get_card(value)
            # Цену считаем ТОЛЬКО на сервере.
            amount = buyer.price(card)
            ok = await state.db.sell_to_buyer(user_id, value, amount)
            title = card.display_name
        elif kind == "inv":
            inventory_id = int(value)
            row = next(
                (r for r in await state.market.user_inventory(user_id) if r["id"] == inventory_id),
                None,
            )
            if row is None:
                raise ValueError("Этой копии у тебя уже нет.")
            card = get_card(row["card_id"])
            amount = buyer.price(card, row["bonus"])
            ok = await state.db.sell_inventory_to_buyer(
                user_id, inventory_id, card.card_id, amount
            )
            title = f"{card.display_name} (улучшенная)"
        else:
            raise ValueError("Не понял, что продаём.")
        if not ok:
            raise ValueError("Этой карты у тебя уже нет.")
    except Exception as error:  # noqa: BLE001
        return JSONResponse({"error": str(error)}, status_code=400)

    return JSONResponse(
        {
            "ok": True,
            "price": amount,
            "title": title,
            "balance": await state.market.balance(user_id),
        }
    )


@router.post("/api/buyer/dupes")
async def api_buyer_dupes(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    user_id = int(user["id"])
    counts = await state.db.get_collection(user_id)
    entries: list[tuple[str, int, int]] = []
    for card_id, count in counts.items():
        if card_id not in CARDS_BY_ID or count <= 1:
            continue
        entries.append((card_id, int(count) - 1, buyer.price(get_card(card_id))))
    if not entries:
        return JSONResponse({"error": "Лишних копий нет."}, status_code=400)

    paid = await state.db.sell_duplicates(user_id, entries)
    return JSONResponse(
        {
            "ok": True,
            "price": paid,
            "balance": await state.market.balance(user_id),
        }
    )


@router.get("/buyer", response_class=HTMLResponse)
async def buyer_app() -> HTMLResponse:
    return HTMLResponse(inject(BUYER_PAGE))


BUYER_PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Северо-Юг · Скупщик</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{
  /* --bg, --ink, --muted, --line приходят из темы игрока и подставляются
     в documentElement. Остальные имена привязываем к тем же переменным,
     иначе на тёмной теме оставались белые пятна. */
  --bg:#f5f3ee; --ink:#1c1a17; --muted:#7c7468; --line:#e6e1d7;
  --card:var(--panel); --gold:var(--acc); --gold2:var(--acc2);
  --soft:color-mix(in srgb, var(--acc) 13%, var(--panel));
  --ok:#3fae6a; --bad:#d8434a;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg);color:var(--ink);min-height:100vh;padding-bottom:96px}
header{position:sticky;top:0;z-index:6;background:color-mix(in srgb,var(--bg) 93%,transparent);
  backdrop-filter:blur(12px);border-bottom:1px solid var(--line);padding:15px 18px 13px}
.hrow{display:flex;align-items:center;justify-content:space-between;gap:12px}
h1{margin:0;font-size:19px;letter-spacing:-.2px}
.sub{font-size:12px;color:var(--muted);margin-top:4px}
.bal{font-weight:800;font-size:15px;background:var(--soft);color:var(--gold);
  border-radius:999px;padding:8px 14px;white-space:nowrap}
.hint{margin:10px 18px 0;background:var(--soft);border:1px solid color-mix(in srgb,var(--acc) 26%,var(--line));
  border-radius:12px;padding:11px 13px;font-size:12.5px;color:var(--ink);line-height:1.5}
.dupes{margin:12px 18px 0}
.dupes button{width:100%;border:0;border-radius:13px;padding:15px;font-size:14.5px;font-weight:800;
  color:#fff;background:linear-gradient(135deg,var(--gold2),var(--gold))}
.dupes button[disabled]{background:var(--panel2);color:var(--muted)}
main{padding:14px 18px}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:11px}
.item{background:var(--card);border:1px solid var(--line);border-radius:15px;overflow:hidden;
  display:flex;flex-direction:column}
.item .pic{
  position:relative;height:104px;overflow:hidden;
  background:linear-gradient(165deg,
    color-mix(in srgb, var(--acc) 20%, var(--panel)) 0%,
    var(--panel2) 70%);
  display:flex;align-items:center;justify-content:center;font-size:38px
}
/* Две волны: цвет берётся из темы, поэтому у каждого стиля свой оттенок */
.item .pic .wave{
  position:absolute;left:0;bottom:-1px;width:200%;height:64%;opacity:.38;z-index:0;
  pointer-events:none;animation:buyerWave 14s linear infinite
}
.item .pic .wave.b{
  height:44%;opacity:.26;animation-duration:21s;animation-direction:reverse
}
.item .pic .wave path{fill:var(--acc)}
.item .pic .wave.b path{fill:var(--acc2)}
/* Лёгкое покачивание голых карточек: заметно, но не мешает */
.item .pic span.art{animation:buyerBob 4.5s ease-in-out infinite}
@keyframes buyerBob{0%,100%{transform:translateY(0)}50%{transform:translateY(-4px)}}
@keyframes buyerWave{from{transform:translateX(0)}to{transform:translateX(-50%)}}
.item .pic .art{position:relative;z-index:1;display:flex;align-items:center;justify-content:center}
.item .pic img.art{width:100%;height:100%;object-fit:cover}
/* Мягкое «дыхание» баланса: медленно и почти незаметно */
@keyframes buyerGlow{
  0%,100%{box-shadow:0 0 0 0 color-mix(in srgb,var(--acc) 0%,transparent)}
  50%{box-shadow:0 0 14px 0 color-mix(in srgb,var(--acc) 26%,transparent)}
}
body .bal{animation:buyerGlow 7s ease-in-out infinite}
@media (prefers-reduced-motion: reduce){
  .item .pic .wave,.item .pic span.art,body .bal{animation:none}
}
.item .body{padding:10px 11px 0}
.item .nm{font-weight:700;font-size:13px;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.item .rr{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.7px;margin-top:3px}
.item .mk{font-size:11px;color:var(--muted);margin-top:6px;text-decoration:line-through}
.item .pr{font-size:16px;font-weight:900;color:var(--gold);margin-top:1px}
.item .sell{margin:9px 10px 10px;border:0;border-radius:11px;padding:11px;font-size:13.5px;
  font-weight:800;color:#fff;background:linear-gradient(135deg,var(--gold2),var(--gold))}
.item .sell:active{transform:scale(.98)}
.item .sell[disabled]{background:var(--panel2);color:var(--muted)}
.item .cnt{font-size:10.5px;color:var(--muted);margin-top:2px}
.empty{text-align:center;color:var(--muted);padding:54px 20px;font-size:14px;line-height:1.6}
#toast{position:fixed;left:14px;right:14px;bottom:16px;background:var(--ink);color:#fff;
  border-radius:12px;padding:14px 16px;font-size:13.5px;line-height:1.45;
  transform:translateY(160%);transition:.26s cubic-bezier(.2,.8,.3,1);z-index:9}
#toast.on{transform:translateY(0)}
#toast.ok{background:var(--ok)} #toast.bad{background:var(--bad)}
</style>
</head>
<body>
<header>
  <div class="hrow">
    <div>
      <h1>Скупщик</h1>
      <div class="sub" id="sub">скупаю любые карты</div>
    </div>
    <div class="bal" id="bal">…</div>
  </div>
</header>
<div class="hint" id="hint">Плачу 90% от рынка — зато сразу и без комиссии.</div>
<div class="dupes" id="dupes"></div>
<main id="list"><div class="empty">Считаю цены…</div></main>
<div id="toast"></div>
<script>
const tg = window.Telegram ? window.Telegram.WebApp : null;
const headers = {"X-Telegram-Init-Data": tg ? tg.initData : "", "Content-Type": "application/json"};
let S = {items: [], balance: 0, busy: false};

function esc(s){ return String(s).replace(/[<>&]/g, c => ({"<":"&lt;",">":"&gt;","&":"&amp;"}[c])); }
function money(n){ return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, " "); }
function toast(t, kind){
  const el = document.getElementById("toast");
  el.textContent = t; el.className = "on " + (kind || "");
  clearTimeout(el._t); el._t = setTimeout(() => el.className = "", 3400);
}
function itemHtml(it){
  const wave = '<svg class="wave" viewBox="0 0 400 60" preserveAspectRatio="none">' +
      '<path d="M0,30 C50,6 100,54 200,30 C300,6 350,54 400,30 L400,60 L0,60 Z" fill="var(--acc)"/></svg>' +
    '<svg class="wave b" viewBox="0 0 400 60" preserveAspectRatio="none">' +
      '<path d="M0,30 C50,6 100,54 200,30 C300,6 350,54 400,30 L400,60 L0,60 Z" fill="var(--acc2)"/></svg>';
  const pic = wave + (it.image
    ? '<img class="art" src="' + it.image + '" alt="">'
    : '<span class="art">' + it.emoji + '</span>');
  const cnt = it.count > 1 ? '<div class="cnt">в коллекции ×' + it.count + '</div>' : '';
  return '<div class="item">' +
    '<div class="pic">' + pic + '</div>' +
    '<div class="body"><div class="nm">' + esc(it.name) + '</div>' +
    '<div class="rr">' + esc(it.rarity) + '</div>' +
    '<div class="mk">рынок ' + money(it.market) + '</div>' +
    '<div class="pr">' + money(it.price) + '</div>' + cnt + '</div>' +
    '<button class="sell" data-ref="' + it.ref + '"' + (S.busy ? " disabled" : "") + '>Продать</button>' +
    '</div>';
}
function render(){
  const list = document.getElementById("list");
  list.innerHTML = S.items.length
    ? '<div class="grid">' + S.items.map(itemHtml).join("") + '</div>'
    : '<div class="empty">Продавать нечего.<br>Выбей карту командой «Северо-Юг».</div>';
  document.querySelectorAll("[data-ref]").forEach(b => b.onclick = () => sell(b.dataset.ref, b));
  document.getElementById("bal").textContent = "$ " + money(S.balance);
}
async function load(){
  try{
    const r = await fetch("/api/buyer", {headers});
    const d = await r.json();
    if (d.error){ toast(d.error, "bad"); return; }
    S.items = d.items; S.balance = d.me.balance;
    document.getElementById("hint").textContent =
      "Плачу " + d.rate + "% от рынка — зато сразу и без комиссии.";
    const dup = document.getElementById("dupes");
    if (d.dupes.count){
      dup.innerHTML = '<button id="dupeBtn">Продать лишние копии (' + d.dupes.count +
        ') за ' + money(d.dupes.total) + '</button>';
      document.getElementById("dupeBtn").onclick = sellDupes;
    } else dup.innerHTML = "";
    render();
  }catch(e){ toast("Не смог загрузить", "bad"); }
}
async function sell(ref, btn){
  if (S.busy) return;
  S.busy = true; btn.disabled = true; btn.textContent = "…";
  try{
    const r = await fetch("/api/buyer/sell", {method:"POST", headers, body: JSON.stringify({ref})});
    const d = await r.json();
    if (d.error) toast(d.error, "bad");
    else {
      toast("💰 " + d.title + " — продано за " + money(d.price), "ok");
      if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
    }
  }catch(e){ toast("Связь потерялась", "bad"); }
  S.busy = false;
  await load();
}
async function sellDupes(){
  if (S.busy) return;
  S.busy = true;
  try{
    const r = await fetch("/api/buyer/dupes", {method:"POST", headers, body: "{}"});
    const d = await r.json();
    if (d.error) toast(d.error, "bad");
    else toast("💰 Лишние копии проданы за " + money(d.price), "ok");
  }catch(e){ toast("Связь потерялась", "bad"); }
  S.busy = false;
  await load();
}
if(tg){ tg.ready(); tg.expand(); }
load();
</script>
</body>
</html>
"""



# --------------------------------------------------------------------------- #
# Стили мини-аппок
# --------------------------------------------------------------------------- #


def _theme_payload(user_id: int, current: str, owned: list[str]) -> dict[str, Any]:
    active = themes.get(current)
    return {
        "theme": active.id,
        "vars": active.vars,
        "particles": active.particles,
        "owned": owned,
        "all": [
            {
                "id": theme.id,
                "name": theme.name,
                "price": theme.price,
                "acc": theme.acc,
                "bg": theme.bg,
                "panel": theme.panel,
                "owned": theme.price == 0 or theme.id in owned,
                "active": theme.id == active.id,
            }
            for theme in themes.THEMES
        ],
    }


@router.get("/api/theme")
async def api_theme(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError:
        # незнакомому отдаём классику, чтобы страница всё равно оформилась
        return JSONResponse(_theme_payload(0, "", []))

    user_id = int(user["id"])
    owned = await state.db.owned_themes(user_id)
    current = await state.db.current_theme(user_id)
    return JSONResponse(_theme_payload(user_id, current, owned))


@router.post("/api/theme/set")
async def api_theme_set(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    user_id = int(user["id"])
    body = await request.json()
    theme_id = str(body.get("theme", ""))
    theme = themes.get(theme_id)
    if theme.id != theme_id:
        return JSONResponse({"error": "Такого стиля нет."}, status_code=400)

    owned = await state.db.owned_themes(user_id)
    if theme.price > 0 and theme.id not in owned:
        return JSONResponse(
            {"error": f"Стиль «{theme.name}» не куплен — он в магазине."}, status_code=400
        )

    await state.db.set_theme(user_id, theme.id)
    return JSONResponse({"ok": True, "theme": theme.id, "payload": _theme_payload(user_id, theme.id, owned)})


# --------------------------------------------------------------------------- #
# Главное приложение игры
# --------------------------------------------------------------------------- #

HUB_SECTIONS: tuple[dict[str, Any], ...] = (
    {"id": "collection", "title": "Коллекция", "note": "все твои карты", "kind": "app", "path": "/collection"},
    {"id": "market", "title": "Рынок", "note": "лоты игроков", "kind": "app", "path": "/market"},
    {"id": "shop", "title": "Магазин", "note": "учителя и наборы", "kind": "app", "path": "/app"},
    {"id": "buyer", "title": "Скупщик", "note": "продать сразу", "kind": "app", "path": "/buyer"},
    {"id": "upgrader", "title": "Апгрейдер", "note": "обмен карт", "kind": "app", "path": "/upgrader"},
    {"id": "cases", "title": "Кейсы", "note": "открыть кейс", "kind": "app", "path": "/case_app"},
    {"id": "roulette", "title": "Рулетка", "note": "крутить колесо", "kind": "app", "path": "/roulette_app"},
    {"id": "casino", "title": "Казино", "note": "кости и ставки", "kind": "app", "path": "/casino_app"},
    {"id": "rtable", "title": "Рулетка-стол", "note": "колесо и шарик", "kind": "app", "path": "/roulette_table"},
    {"id": "yugi", "title": "Юга-кликер", "note": "тапай и качай", "kind": "app", "path": "/yugi"},
    {"id": "dungeon", "title": "Подземелье", "note": "мобы и кооп-босс", "kind": "app", "path": "/proto_dungeon"},
    {"id": "quests", "title": "Задания", "note": "квесты и награды", "kind": "app", "path": "/quests"},
    {"id": "stocks", "title": "Биржа", "note": "курсы и акции", "kind": "app", "path": "/stocks"},
    {"id": "top", "title": "Топ", "note": "по очкам", "kind": "panel"},
    {"id": "levels", "title": "Уровни", "note": "кто выше", "kind": "panel"},
    {"id": "profile", "title": "Профиль", "note": "бои и репутация", "kind": "panel"},
    {"id": "style", "title": "Стиль", "note": "оформление", "kind": "panel"},
)


@router.get("/api/hub")
async def api_hub(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    user_id = int(user["id"])
    stocks: list[dict[str, Any]] = []
    if getattr(state, "stocks", None) is not None:
        try:
            data = await state.stocks.overview(user_id)
            for item in data["stocks"]:
                stocks.append(
                    {
                        "name": item["name"],
                        "emoji": item["emoji"],
                        "price": item["price"],
                        "change": item["change"],
                        "buy_price": item["buy_price"],
                        "sell_price": item["sell_price"],
                        "pump": item["pump"],
                        "history": [int(v) for v in item["history"][-60:]],
                    }
                )
        except Exception:  # noqa: BLE001
            log.exception("Хаб: биржа не ответила")

    counts = await state.db.get_collection(user_id)
    cards = []
    for card in cards_sorted_for_user(list(counts)):
        payload = upgrader.card_payload(card, counts[card.card_id])
        payload["ref"] = f"card:{card.card_id}"
        cards.append(payload)

    profile = await state.db.player_profile(user_id) or {}
    owned = await state.db.owned_themes(user_id)

    return JSONResponse(
        {
            "me": {
                "name": user.get("first_name") or "игрок",
                "balance": await state.market.balance(user_id),
                # Уровень в базе не хранится — он считается из опыта.
            # Раньше тут читалось несуществующее поле, и у всех был «1».
            "level": levels.level_from_xp(int(profile.get("xp") or 0)),
                "xp": int(profile.get("xp") or 0),
                "wins": int(profile.get("wins") or 0),
                "cards": len(cards),
            },
            "stocks": stocks,
            "collection": cards,
            "top": await state.db.top_players(10),
            "levels": await state.db.level_top(10),
            "themes": {
                "current": themes.get(await state.db.current_theme(user_id)).id,
                "owned": owned,
                "all": [
                    {
                        "id": theme.id,
                        "name": theme.name,
                        "price": theme.price,
                        "acc": theme.acc,
                        "bg": theme.bg,
                        "owned": theme.price == 0 or theme.id in owned,
                    }
                    for theme in themes.THEMES
                ],
            },
            "sections": [
                dict(section, url=f"{request.base_url}".rstrip("/"))
                for section in (
                    [
                        {
                            "id": "quests",
                            "title": "ЗАДАНИЯ",
                            "note": "квесты и PvP",
                            "kind": "app",
                            "path": "/quests",
                        }
                    ]
                    + (
                        [
                            {
                                "id": "event",
                                "title": "СОБЫТИЕ",
                                "note": "Звёздочка",
                                "kind": "app",
                                "path": "/event",
                            }
                        ]
                        if (await state.db.event_state()).get("active")
                        else []
                    )
                    + list(HUB_SECTIONS)
                )
            ],
        }
    )


@router.get("/hub", response_class=HTMLResponse)
async def hub_app() -> HTMLResponse:
    return HTMLResponse(inject(HUB_PAGE))


HUB_PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<title>Северо-Юг</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{
  --bg:#1b1613; --panel:#241d19; --panel2:#2e251f; --line:#3d3229;
  --ink:#f4ece4; --muted:#a8968a; --acc:#dc8a3f; --acc2:#f0b276; --acc-ink:#1b1206;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0;overscroll-behavior:none}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg);color:var(--ink);min-height:100vh;padding-bottom:28px}
.top{display:flex;align-items:center;justify-content:space-between;gap:10px;
  padding:15px 16px 13px;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:8;
  background:color-mix(in srgb,var(--bg) 90%,transparent);backdrop-filter:blur(12px)}
.brand{font-weight:900;letter-spacing:2.5px;font-size:15px}
.brand i{color:var(--acc);font-style:normal}
.chips{display:flex;gap:7px;align-items:center}
.chip{background:var(--panel);border:1px solid var(--line);border-radius:999px;
  padding:7px 12px;font-size:12.5px;font-weight:800;white-space:nowrap}
.chip.bal{color:var(--acc2)}
.chip.lvl{color:var(--ink)}

.wrap{padding:14px 15px 0;max-width:560px;margin:0 auto}

.tickwrap{margin:2px 0 20px;position:relative;padding-bottom:16px}
.tickwrap::after{content:"";position:absolute;left:-15px;right:-15px;bottom:0;height:1px;
  background:linear-gradient(90deg,transparent,var(--acc) 22%,var(--acc2) 50%,var(--acc) 78%,transparent);
  opacity:.55}
.tickwrap::before{content:"";position:absolute;left:0;right:0;bottom:-14px;height:28px;
  background:radial-gradient(60% 100% at 50% 0%,color-mix(in srgb,var(--acc) 16%,transparent),transparent 72%);
  pointer-events:none}
.market{display:flex;flex-direction:column;gap:6px;transition:opacity .5s ease,transform .5s ease}
.market.out{opacity:0;transform:translateY(-9px)}
/* Сетка вместо flex: цены больше не выпирают за края.
   minmax(0, ...) разрешает блокам сжиматься, а шрифт подстраивается. */
.mk-top{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.15fr) minmax(0,1fr);
  align-items:center;gap:8px;width:100%}
.mk-side{display:flex;flex-direction:column;gap:2px;min-width:0;overflow:hidden}
.mk-side:first-child{align-items:flex-start;text-align:left}
.mk-side:last-child{align-items:flex-end;text-align:right}
.mk-side b{font-size:clamp(14px,4.3vw,20px);font-weight:900;letter-spacing:-.5px;
  line-height:1.05;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  max-width:100%;display:block}
.mk-side span{font-size:10px;letter-spacing:1.1px;text-transform:uppercase;
  color:var(--muted);font-weight:700;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;max-width:100%}
.mk-name{min-width:0;text-align:center;font-size:clamp(15px,4.7vw,21px);font-weight:900;
  letter-spacing:-.3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mk-rate{text-align:center;font-size:19px;font-weight:900;letter-spacing:.2px;color:#7fd0a0}
.mk-rate.down{color:#e28d92}
.mkcv{display:block;width:100%;height:84px;margin-top:10px;overflow:visible}
.mk-dots{display:flex;gap:5px;justify-content:center;margin-top:7px}
.mk-dots i{width:16px;height:3px;border-radius:99px;background:var(--line);display:block;transition:.3s}
.mk-dots i.on{background:var(--acc);width:26px}

.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:15px;padding:14px 13px;
  text-align:left;display:flex;flex-direction:column;gap:4px;position:relative;overflow:hidden}
.tile::before{content:"";position:absolute;left:0;right:0;top:0;height:2px;
  background:linear-gradient(90deg,var(--acc),transparent 70%);opacity:.75}
.tile .tt{font-size:14.5px;font-weight:800;letter-spacing:.2px}
.tile .tn{font-size:11.5px;color:var(--muted)}
.tile:active{transform:scale(.975)}

.panel{display:none}
.panel.on{display:block}
.phead{display:flex;align-items:center;justify-content:space-between;margin:2px 0 12px}
.phead b{font-size:16px;font-weight:900}
.back{border:1px solid var(--line)!important;background:transparent!important;color:var(--muted)!important;
  border-radius:10px!important;padding:9px 14px!important;font-size:12.5px!important;box-shadow:none!important}

.list{display:flex;flex-direction:column;gap:8px}
.line{display:flex;align-items:center;gap:11px;background:var(--panel);border:1px solid var(--line);
  border-radius:12px;padding:11px 13px}
.line .pos{font-size:13px;font-weight:900;color:var(--acc2);min-width:24px}
.line .nm{flex:1;font-size:13.5px;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.line .vl{font-size:12.5px;font-weight:800;color:var(--muted);white-space:nowrap}
.cgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}
.cgrid .card{background:var(--panel);border:1.5px solid var(--line);border-radius:12px;padding:7px;text-align:center}
.cgrid img{width:100%;height:54px;object-fit:cover;border-radius:8px;display:block}
.cgrid .ic{font-size:29px;line-height:54px}
.cgrid .nm{font-size:10.5px;font-weight:700;margin-top:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cgrid .pr{font-size:9.5px;color:var(--acc2);font-weight:700}
.r-rare{border-color:rgba(107,114,128,.55)!important} .r-superrare{border-color:rgba(59,130,246,.7)!important}
.r-epic{border-color:rgba(168,85,247,.75)!important} .r-mythic{border-color:rgba(239,68,68,.75)!important}
.r-legendary{border-color:rgba(234,179,8,.8)!important} .r-secret{border-color:rgba(100,116,139,.85)!important}
.r-ultra{border-color:rgba(232,121,249,.9)!important} .r-teacher{border-color:rgba(194,65,12,.9)!important}

.theme{display:flex;align-items:center;gap:11px;background:var(--panel);border:1px solid var(--line);
  border-radius:12px;padding:11px;width:100%;text-align:left}
.theme.on{border-color:var(--acc)}
.sw{display:flex;gap:3px;flex:0 0 auto}
.sw i{width:15px;height:22px;border-radius:5px;display:block}
.theme .nm{flex:1;font-weight:700;font-size:13.5px}
.theme .pc{font-size:12px;font-weight:800;color:var(--acc2)}
.empty{color:var(--muted);font-size:13px;line-height:1.6;text-align:center;padding:34px 14px;
  border:1px dashed var(--line);border-radius:14px}
#toast{position:fixed;left:14px;right:14px;bottom:16px;background:var(--panel2);color:var(--ink);
  border:1px solid var(--line);border-radius:12px;padding:13px 15px;font-size:13px;
  transform:translateY(200%);transition:.25s;z-index:30}
#toast.on{transform:translateY(0)}

/* профиль в приложении: та же карточка, что в мини-апп */
.line.tap{cursor:pointer}
.line.tap:active{background:var(--panel2)}
.line .go{color:var(--muted);font-weight:900;font-size:16px;margin-left:6px}
.pcard{background:var(--panel);border:1px solid var(--line);border-radius:16px;
  overflow:hidden;margin-bottom:12px}
.pbn{height:84px}
.pav{position:relative;margin:-26px 0 0 14px;width:62px;height:62px;border-radius:18px;
  display:flex;align-items:center;justify-content:center;font-size:24px;font-weight:900;
  border:3px solid var(--panel);box-shadow:0 4px 14px #0006;overflow:hidden}
.pav img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.pbody{padding:10px 14px 14px}
.pnm{font-size:17px;font-weight:900}
.pst{font-size:12px;color:var(--acc2);margin-top:3px;font-weight:700}
.pbio{font-size:12px;margin-top:8px;line-height:1.5;opacity:.85}
.ptags{display:flex;gap:5px;flex-wrap:wrap;margin-top:10px}
.ptags span{font-size:10px;font-weight:800;padding:3px 8px;border-radius:99px;
  background:color-mix(in srgb,var(--acc) 16%,transparent);color:var(--acc2)}
.prew{font-size:12px;margin-top:9px;line-height:1.6;color:var(--muted)}
.pgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px}
.pgrid>div{background:var(--panel2);border:1px solid var(--line);border-radius:12px;
  padding:9px 6px;text-align:center}
.pgrid b{display:block;font-size:17px;font-weight:900}
.pgrid span{font-size:9px;letter-spacing:.7px;text-transform:uppercase;color:var(--muted);
  font-weight:800}
.prow{display:flex;gap:8px;margin-top:12px}
.prow button{flex:1;border-radius:12px;padding:11px;font-size:12.5px;font-weight:800}
.psearch{display:flex;gap:8px;margin:4px 0 2px}
.psearch input{flex:1;background:var(--panel2);border:1px solid var(--line);border-radius:12px;
  color:var(--ink);padding:11px 13px;font-size:13px}
.psearch button{border:0;border-radius:12px;padding:0 16px;font-size:12.5px;font-weight:800}
.pres{display:flex;align-items:center;gap:10px;background:var(--panel);
  border:1px solid var(--line);border-radius:12px;padding:9px 11px;margin-top:8px;cursor:pointer}
.pres:active{background:var(--panel2)}
.pres .a{width:34px;height:34px;border-radius:10px;display:flex;align-items:center;
  justify-content:center;font-weight:900;font-size:14px;flex:0 0 auto}
.pres .n{flex:1;min-width:0;font-size:13px;font-weight:800;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
.pres .l{font-size:11px;color:var(--muted);font-weight:700}
</style>
</head>
<body>
<div class="top">
  <div class="brand">СЕВЕРО<i>/</i>ЮГ</div>
  <div class="chips">
    <div class="chip lvl" id="lvl">ур. …</div>
    <div class="chip bal" id="bal">…</div>
  </div>
</div>

<div class="wrap">
  <section class="panel on" id="p-home">
    <div class="tickwrap">
      <div class="market" id="market"></div>
      <svg class="mkcv" id="mkcv" viewBox="0 0 320 92" preserveAspectRatio="none"></svg>
      <div class="mk-dots" id="mkDots"></div>
    </div>
    <div class="grid" id="tiles"></div>
  </section>

  <section class="panel" id="p-collection">
    <div class="phead"><b>Коллекция</b><button class="back" data-home>Назад</button></div>
    <div class="cgrid" id="collGrid"></div>
  </section>

  <section class="panel" id="p-top">
    <div class="phead"><b>Топ по очкам</b><button class="back" data-home>Назад</button></div>
    <div class="list" id="topList"></div>
  </section>

  <section class="panel" id="p-levels">
    <div class="phead"><b>Топ по уровням</b><button class="back" data-home>Назад</button></div>
    <div class="list" id="lvlList"></div>
  </section>

  <section class="panel" id="p-profile">
    <div class="phead"><b>Профиль</b><button class="back" data-home>Назад</button></div>
    <div class="list" id="profList"></div>
  </section>

  <section class="panel" id="p-style">
    <div class="phead"><b>Стиль</b><button class="back" data-home>Назад</button></div>
    <div class="list" id="themeList"></div>
  </section>
</div>

<div id="toast"></div>
<script>
const tg = window.Telegram ? window.Telegram.WebApp : null;
const headers = {"X-Telegram-Init-Data": tg ? tg.initData : "", "Content-Type": "application/json"};
let S = {data: null};

function esc(s){ return String(s).replace(/[<>&]/g, c => ({"<":"&lt;",">":"&gt;","&":"&amp;"}[c])); }
function money(n){ return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, " "); }
function toast(t){
  const el = document.getElementById("toast");
  el.textContent = t; el.className = "on";
  clearTimeout(el._t); el._t = setTimeout(() => el.className = "", 2600);
}
function show(id){
  document.querySelectorAll(".panel").forEach(p => p.classList.remove("on"));
  document.getElementById(id).classList.add("on");
  window.scrollTo({top:0, behavior:"smooth"});
}
let mkIndex = 0, mkTimer = null;
function drawMini(s){
  const el = document.getElementById("mkcv");
  if (!el) return;
  const hist = (s && s.history) || [];
  el.innerHTML = "";
  if (hist.length < 3) return;
  const size = Math.max(2, Math.ceil(hist.length / 22));
  const bars = [];
  for (let i = 0; i < hist.length; i += size){
    const ch = hist.slice(i, i + size);
    if (!ch.length) continue;
    bars.push({o: ch[0], c: ch[ch.length - 1],
               h: Math.max.apply(null, ch), l: Math.min.apply(null, ch)});
  }
  const hi = Math.max.apply(null, bars.map(b => b.h));
  const lo = Math.min.apply(null, bars.map(b => b.l));
  const pad = (hi - lo) * 0.15 || 1;
  const top = hi + pad, bot = lo - pad;
  const n = bars.length, w = 320 / n, bw = Math.max(4, w * 0.66);
  const y = v => 6 + (1 - (v - bot) / (top - bot)) * 80;
  let svg = "";
  bars.forEach((b, i) => {
    const x = i * w + w / 2;
    const up = b.c >= b.o;
    const col = up ? "#9dc941" : "#e0407a";
    svg += '<line x1="' + x + '" y1="' + y(b.h) + '" x2="' + x + '" y2="' + y(b.l) +
      '" stroke="' + col + '" stroke-width="1"/>';
    const y1 = Math.min(y(b.o), y(b.c)), y2 = Math.max(y(b.o), y(b.c));
    svg += '<rect x="' + (x - bw / 2) + '" y="' + y1 + '" width="' + bw + '" height="' +
      Math.max(2.5, y2 - y1) + '" fill="' + col + '" rx="1.5"/>';
  });
  el.innerHTML = svg;
}
function paintCoin(){
  const list = S.data.stocks;
  const box = document.getElementById("market");
  if (!list.length){ box.innerHTML = '<div class="empty">Биржа молчит</div>'; return; }
  const s = list[mkIndex % list.length];
  const down = s.change < 0;
  box.innerHTML =
    '<div class="mk-top">' +
      '<div class="mk-side"><b>' + money(s.buy_price) + '</b><span>покупка</span></div>' +
      '<div class="mk-name">' + esc(s.name) + '</div>' +
      '<div class="mk-side"><b>' + money(s.sell_price) + '</b><span>продажа</span></div>' +
    '</div>' +
    '<div class="mk-rate' + (down ? " down" : "") + '">' +
      (down ? "" : "+") + s.change + '%' +
      (s.pump ? "  ▲" : "") + '</div>';
  drawMini(s);
  document.getElementById("mkDots").innerHTML = list.map((_, i) =>
    '<i class="' + (i === mkIndex % list.length ? "on" : "") + '"></i>').join("");
}
function renderTicker(){
  paintCoin();
  clearInterval(mkTimer);
  mkTimer = setInterval(() => {
    const list = S.data.stocks;
    if (!list.length) return;
    const box = document.getElementById("market");
    box.classList.add("out");
    setTimeout(() => {
      mkIndex = (mkIndex + 1) % list.length;
      paintCoin();
      box.classList.remove("out");
    }, 500);
  }, 5000);
}
function renderTiles(){
  document.getElementById("tiles").innerHTML = S.data.sections.map(sec =>
    '<div class="tile" data-sec="' + sec.id + '"><div class="tt">' + esc(sec.title) +
    '</div><div class="tn">' + esc(sec.note) + '</div></div>').join("");
  document.querySelectorAll("[data-sec]").forEach(el => el.onclick = () => open(el.dataset.sec));
  document.querySelectorAll("[data-home]").forEach(b => b.onclick = () => show("p-home"));
}
function open(id){
  const sec = S.data.sections.find(s => s.id === id);
  if (!sec) return;
  if (sec.kind === "app" && sec.path){
    if (tg && tg.HapticFeedback) tg.HapticFeedback.selectionChanged();
    window.location.href = sec.path;
    return;
  }
  if (id === "collection"){
    const mine = S.data.collection;
    document.getElementById("collGrid").innerHTML = mine.length
      ? mine.map(c => '<div class="card r-' + c.rarity_key + '">' +
          (c.image ? '<img src="' + c.image + '">' : '<div class="ic">' + c.emoji + '</div>') +
          '<div class="nm">' + esc(c.name) + '</div>' +
          '<div class="pr">' + money(c.price) + (c.count > 1 ? " ×" + c.count : "") + '</div></div>').join("")
      : '<div class="empty" style="grid-column:1/-1">Пусто. Выбей карту командой «Северо-Юг».</div>';
    show("p-collection");
  } else if (id === "top" || id === "levels"){
    const rows = id === "top" ? S.data.top : S.data.levels;
    const box = document.getElementById(id === "top" ? "topList" : "lvlList");
    box.innerHTML = rows.length ? rows.map((r, i) => {
      const name = esc(r.first_name || r.username || "игрок");
      const value = id === "top"
        ? money(r.points) + " очк."
        : "ур. " + r.level + " · " + r.xp + " xp";
      // тап по строке открывает профиль этого игрока, не выходя из приложения
      return '<div class="line tap" data-u="' + (r.user_id || r.id) + '">' +
        '<div class="pos">' + (i + 1) + '</div><div class="nm">' + name +
        '</div><div class="vl">' + value + '</div><div class="go">›</div></div>';
    }).join("") : '<div class="empty">Пока пусто</div>';
    box.querySelectorAll("[data-u]").forEach(el => el.onclick = () => {
      loadProfile(+el.dataset.u);
      show("p-profile");
    });
    show(id === "top" ? "p-top" : "p-levels");
  } else if (id === "profile"){
    loadProfile(0);
    show("p-profile");
  } else if (id === "style"){
    renderThemes();
    show("p-style");
  }
}
async function loadProfile(userId){
  const box = document.getElementById("profList");
  box.innerHTML = '<div class="empty">Загружаю…</div>';
  try{
    const r = await fetch("/api/profile" + (userId ? "?u=" + userId : ""), {headers});
    const d = await r.json();
    if (d.error){ box.innerHTML = '<div class="empty">' + esc(d.error) + '</div>'; return; }
    const tags = (d.tags || []).map(t => '<span>' + esc(t.label) + '</span>').join("");
    const rewards = (d.rewards || []).length
      ? '<div class="prew">' + d.rewards.map(rw => esc(rw.icon) + " " + esc(rw.text)).join("<br>") + '</div>'
      : "";
    box.innerHTML =
      '<div class="pcard">' +
        '<div class="pbn" style="background:' + d.banner_css + '"></div>' +
        '<div class="pav" style="background:' + d.avatar_color + '">' +
          esc(d.initial) +
          (d.avatar ? '<img src="' + esc(d.avatar) + '" alt="" onerror="this.remove()">' : '') +
        '</div>' +
        '<div class="pbody">' +
          '<div class="pnm">' + esc(d.name) + (d.vip ? ' 👑' : "") + '</div>' +
          (d.status ? '<div class="pst">' + esc(d.status) + '</div>' : '') +
          (d.bio ? '<div class="pbio">' + esc(d.bio) + '</div>' : '') +
          (tags ? '<div class="ptags">' + tags + '</div>' : '') +
          rewards +
          '<div class="pgrid">' +
            '<div><b>' + d.level + '</b><span>уровень</span></div>' +
            '<div><b>' + d.wins + '</b><span>побед</span></div>' +
            '<div><b>' + d.cards + '</b><span>карт</span></div>' +
          '</div>' +
          '<div class="prow">' +
            (d.is_me ? '<button id="profEdit">Настроить</button>'
                     : '<button id="profSelf">Мой профиль</button>') +
            '<button id="profFull">Открыть страницу</button>' +
          '</div>' +
        '</div>' +
      '</div>' +
      '<div class="psearch"><input id="profQ" placeholder="Найти игрока" maxlength="40">' +
      '<button id="profGo">Найти</button></div>' +
      '<div id="profRes"></div>';
    const edit = document.getElementById("profEdit");
    if (edit) edit.onclick = () => { location.href = "/profile"; };
    const self = document.getElementById("profSelf");
    if (self) self.onclick = () => loadProfile(0);
    document.getElementById("profFull").onclick = () => {
      location.href = d.is_me ? "/profile" : "/profile?u=" + d.id;
    };
    document.getElementById("profGo").onclick = profSearch;
    document.getElementById("profQ").addEventListener("keydown", e => {
      if (e.key === "Enter") profSearch();
    });
    S.profId = d.id;
  }catch(e){ box.innerHTML = '<div class="empty">Не смог загрузить</div>'; }
}
async function profSearch(){
  const q = (document.getElementById("profQ").value || "").trim();
  const box = document.getElementById("profRes");
  if (q.length < 2){ box.innerHTML = '<div class="empty">Хотя бы две буквы</div>'; return; }
  try{
    const r = await fetch("/api/profile/search?q=" + encodeURIComponent(q), {headers});
    const d = await r.json();
    if (d.error){ box.innerHTML = '<div class="empty">' + esc(d.error) + '</div>'; return; }
    if (!d.results.length){ box.innerHTML = '<div class="empty">Никого не нашёл</div>'; return; }
    box.innerHTML = d.results.map(u =>
      '<div class="pres" data-u="' + u.id + '">' +
      '<div class="a" style="background:' + u.color + '">' + esc(u.initial) + '</div>' +
      '<div class="n">' + esc(u.name) + '</div>' +
      '<div class="l">ур. ' + u.level + '</div></div>').join("");
    box.querySelectorAll("[data-u]").forEach(el => el.onclick = () => loadProfile(+el.dataset.u));
  }catch(e){ box.innerHTML = '<div class="empty">Связь потерялась</div>'; }
}
function renderThemes(){
  const t = S.data.themes;
  document.getElementById("themeList").innerHTML = t.all.map(th => {
    const state = th.id === t.current ? " on" : "";
    const price = th.price === 0 ? "бесплатно" : (th.owned ? "куплен" : money(th.price) + " очк.");
    return '<button class="theme' + state + '" data-theme="' + th.id + '">' +
      '<span class="sw"><i style="background:' + th.bg + '"></i>' +
      '<i style="background:' + th.acc + '"></i></span>' +
      '<span class="nm">' + esc(th.name) + '</span>' +
      '<span class="pc">' + price + '</span></button>';
  }).join("");
  document.querySelectorAll("[data-theme]").forEach(b => b.onclick = () => pickTheme(b.dataset.theme));
}
async function pickTheme(id){
  try{
    const r = await fetch("/api/theme/set", {method:"POST", headers, body: JSON.stringify({theme:id})});
    const d = await r.json();
    if (d.error){ toast(d.error); return; }
    toast("Стиль включён");
    if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
    setTimeout(() => window.location.reload(), 400);
  }catch(e){ toast("Связь потерялась"); }
}
async function load(){
  try{
    const r = await fetch("/api/hub", {headers});
    const d = await r.json();
    if (d.error){ toast(d.error); return; }
    S.data = d;
    document.getElementById("bal").textContent = "$ " + money(d.me.balance);
    document.getElementById("lvl").textContent = "ур. " + d.me.level;
    renderTicker(); renderTiles();
  }catch(e){ toast("Не смог загрузить"); }
}
if(tg){ tg.ready(); tg.expand(); }
load();
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# Казино — мини-аппка
# --------------------------------------------------------------------------- #


def _casino_games() -> list[dict[str, Any]]:
    dice: list[dict[str, Any]] = [
        {"id": "even", "label": "Чёт", "mult": 2},
        {"id": "odd", "label": "Нечёт", "mult": 2},
    ]
    dice += [{"id": f"d{i}", "label": str(i), "mult": 3} for i in range(1, 7)]
    shots = [
        {"id": "hit", "label": "Попадёт", "mult": 2},
        {"id": "miss", "label": "Не попадёт", "mult": 2},
    ]
    return [
        {"id": "dice", "title": "Кости", "emoji": "🎲", "faces": 6, "choices": dice},
        {"id": "football", "title": "Футбол", "emoji": "⚽", "faces": 5, "choices": shots},
        {"id": "basketball", "title": "Баскетбол", "emoji": "🏀", "faces": 5, "choices": shots},
    ]


@router.get("/api/casino")
async def api_casino(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    user_id = int(user["id"])
    left = await state.db.casino_left(user_id, roulette_day_key(), casino.SPINS_PER_DAY)
    return JSONResponse(
        {
            "me": {
                "balance": await state.market.balance(user_id),
                "left": left,
                "cap": casino.SPINS_PER_DAY,
            },
            "limits": {"min": casino.MIN_BET, "max": casino.MAX_BET},
            "games": _casino_games(),
        }
    )


@router.post("/api/casino/play")
async def api_casino_play(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    user_id = int(user["id"])
    body = await request.json()
    game = str(body.get("game", ""))
    choice = str(body.get("choice", ""))
    try:
        bet = int(body.get("bet", 0))
    except (TypeError, ValueError):
        return JSONResponse({"error": "Не понял ставку"}, status_code=400)

    if game not in dice_casino.GAMES or not dice_casino.is_choice_valid(game, choice):
        return JSONResponse({"error": "Не понял выбор"}, status_code=400)
    if not casino.MIN_BET <= bet <= casino.MAX_BET:
        return JSONResponse(
            {"error": f"Ставка от {casino.MIN_BET} до {casino.MAX_BET} очков"},
            status_code=400,
        )
    balance = await state.market.balance(user_id)
    if balance < bet:
        return JSONResponse(
            {"error": f"Не хватает очков: ставишь {bet}, у тебя {balance}"}, status_code=400
        )

    left = await state.db.claim_casino(user_id, roulette_day_key(), casino.SPINS_PER_DAY)
    if left is None:
        return JSONResponse(
            {"error": "Крутки на сегодня кончились"}, status_code=400
        )

    value = random.randint(1, dice_casino.face_count(game))
    won = dice_casino.is_win(game, choice, value)
    mult = dice_casino.multiplier(game, choice)
    try:
        await CasinoRepo(state.db, state.market).play_points(
            user_id, bet, won, mult, game, choice, value
        )
    except Exception as error:  # noqa: BLE001
        return JSONResponse({"error": str(error)}, status_code=400)

    return JSONResponse(
        {
            "ok": True,
            "won": won,
            "value": value,
            "mult": mult,
            "bet": bet,
            "payout": bet * mult if won else 0,
            "delta": (bet * mult if won else 0) - bet,
            "game": game,
            "choice": choice,
            "choice_label": dice_casino.choice_label(game, choice),
            "balance": await state.market.balance(user_id),
            "left": await state.db.casino_left(user_id, roulette_day_key(), casino.SPINS_PER_DAY),
        }
    )


@router.get("/casino_app", response_class=HTMLResponse)
async def casino_app() -> HTMLResponse:
    return HTMLResponse(inject(CASINO_PAGE))
CASINO_PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<title>Северо-Юг · Казино</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{--up:#3fae6a;--down:#d8434a}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0;overscroll-behavior:none}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg);color:var(--ink);min-height:100vh;padding-bottom:26px}
.wrap{max-width:520px;margin:0 auto;padding:14px}

.plate{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px;text-align:center;
  position:relative;overflow:hidden}
.plate::before{content:"";position:absolute;left:0;right:0;top:0;height:2px;
  background:linear-gradient(90deg,transparent,var(--acc),transparent)}
.plate .cap{font-size:10.5px;letter-spacing:1.4px;text-transform:uppercase;color:var(--muted);font-weight:800}
.plate .big{font-size:76px;line-height:1.05;margin:6px 0 2px;transition:transform .12s}
.plate .big.roll{animation:shake .28s infinite}
@keyframes shake{0%{transform:translateY(0) rotate(-7deg)}50%{transform:translateY(-8px) rotate(7deg)}100%{transform:translateY(0) rotate(-7deg)}}
.plate .val{font-size:15px;font-weight:900;letter-spacing:.4px;min-height:20px}
.plate .sub{font-size:12px;color:var(--muted);margin-top:5px;min-height:16px}
.win{color:var(--up)} .lose{color:var(--down)}

.tabs{display:flex;gap:8px;margin:14px 0 10px}
.tab{flex:1;border:1px solid var(--line);background:var(--panel);color:var(--muted);
  border-radius:12px;padding:12px 6px;font-size:13px;font-weight:800}
.tab.on{background:var(--acc);color:var(--acc-ink);border-color:transparent}
.tab small{display:block;font-size:10px;font-weight:700;opacity:.75;margin-top:2px}

.block{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px;margin-bottom:11px}
.block .t{font-size:10.5px;letter-spacing:1.3px;text-transform:uppercase;color:var(--muted);font-weight:800;margin-bottom:9px}
.choices{display:flex;flex-wrap:wrap;gap:7px}
.ch{border:1px solid var(--line);background:transparent;color:var(--muted);border-radius:11px;
  padding:11px 14px;font-size:14px;font-weight:800;min-width:60px}
.ch.on{background:var(--acc);color:var(--acc-ink);border-color:transparent}
.ch i{display:block;font-style:normal;font-size:10px;font-weight:700;opacity:.8}
.bets{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}
.bet{border:1px solid var(--line);background:transparent;color:var(--muted);border-radius:11px;
  padding:11px 4px;font-size:13px;font-weight:800}
.bet.on{background:var(--acc);color:var(--acc-ink);border-color:transparent}
.custom{display:flex;gap:7px;margin-top:8px}
.custom input{flex:1;background:var(--panel2);border:1px solid var(--line);border-radius:11px;
  color:var(--ink);padding:11px 13px;font-size:15px;font-weight:800;font-family:inherit}
.custom button{border:1px solid var(--line);background:transparent;color:var(--muted);
  border-radius:11px;padding:0 16px;font-size:13px;font-weight:800}

.spin{width:100%;border:0;border-radius:15px;padding:18px;font-size:17px;font-weight:900;
  letter-spacing:1px;color:var(--acc-ink);background:var(--acc);margin-top:4px}
.spin[disabled]{background:var(--panel2);color:var(--muted)}
.foot{display:flex;justify-content:space-between;font-size:11.5px;color:var(--muted);margin-top:10px;padding:0 3px}
#toast{position:fixed;left:14px;right:14px;bottom:16px;background:var(--panel2);color:var(--ink);
  border:1px solid var(--line);border-radius:12px;padding:13px 15px;font-size:13px;
  transform:translateY(220%);transition:.25s;z-index:30}
#toast.on{transform:translateY(0)}
</style>
</head>
<body>
<div class="wrap">
  <div class="plate">
    <div class="cap" id="cap">Кости</div>
    <div class="big" id="face">🎲</div>
    <div class="val" id="val">&nbsp;</div>
    <div class="sub" id="sub">выбери игру, ставку и жми</div>
  </div>

  <div class="tabs" id="tabs"></div>

  <div class="block">
    <div class="t">На что ставим</div>
    <div class="choices" id="choices"></div>
  </div>

  <div class="block">
    <div class="t">Ставка</div>
    <div class="bets" id="bets"></div>
    <div class="custom">
      <input id="betInput" type="number" inputmode="numeric" placeholder="своя сумма">
      <button id="betSet">ОК</button>
    </div>
  </div>

  <button class="spin" id="spin">КРУТИТЬ</button>
  <div class="foot">
    <span id="bal">…</span>
    <span id="left">…</span>
  </div>
</div>
<div id="toast"></div>
<script>
const tg = window.Telegram ? window.Telegram.WebApp : null;
const headers = {"X-Telegram-Init-Data": tg ? tg.initData : "", "Content-Type": "application/json"};
const PRESETS = [100, 500, 1000, 5000];
let S = {data: null, game: null, choice: null, bet: 500, busy: false};

function esc(s){ return String(s).replace(/[<>&]/g, c => ({"<":"&lt;",">":"&gt;","&":"&amp;"}[c])); }
function money(n){ return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, " "); }
function toast(t){
  const el = document.getElementById("toast");
  el.textContent = t; el.className = "on";
  clearTimeout(el._t); el._t = setTimeout(() => el.className = "", 3000);
}
function curGame(){ return S.data.games.find(g => g.id === S.game); }
function render(){
  const g = curGame();
  document.getElementById("tabs").innerHTML = S.data.games.map(x =>
    '<button class="tab' + (x.id === S.game ? " on" : "") + '" data-g="' + x.id + '">' +
    x.title + '<small>' + x.emoji + '</small></button>').join("");
  document.getElementById("choices").innerHTML = g.choices.map(c =>
    '<button class="ch' + (c.id === S.choice ? " on" : "") + '" data-c="' + c.id + '">' +
    esc(c.label) + '<i>×' + c.mult + '</i></button>').join("");
  document.getElementById("bets").innerHTML = PRESETS.map(b =>
    '<button class="bet' + (S.bet === b ? " on" : "") + '" data-b="' + b + '">' + money(b) + '</button>').join("");
  document.getElementById("cap").textContent = g.title;
  document.getElementById("face").textContent = g.emoji;
  document.getElementById("bal").textContent = "Баланс $ " + money(S.data.me.balance);
  document.getElementById("left").textContent = "Круток: " + S.data.me.left + " / " + S.data.me.cap;
  document.getElementById("spin").disabled = S.busy || !S.choice;
  document.querySelectorAll("[data-g]").forEach(el => el.onclick = () => {
    S.game = el.dataset.g; S.choice = curGame().choices[0].id; render();
  });
  document.querySelectorAll("[data-c]").forEach(el => el.onclick = () => { S.choice = el.dataset.c; render(); });
  document.querySelectorAll("[data-b]").forEach(el => el.onclick = () => {
    S.bet = +el.dataset.b; document.getElementById("betInput").value = ""; render();
  });
}
function setFace(text, cls){
  const f = document.getElementById("face");
  f.textContent = text; f.className = "big" + (cls ? " " + cls : "");
}
async function spin(){
  if (S.busy || !S.choice) return;
  S.busy = true; render();
  const f = document.getElementById("face");
  f.classList.add("roll");
  document.getElementById("val").textContent = "";
  document.getElementById("sub").textContent = "крутится…";
  const g = curGame();
  const faces = g.emoji;
  const shuffler = setInterval(() => { f.textContent = faces; }, 90);
  try{
    const r = await fetch("/api/casino/play", {method:"POST", headers,
      body: JSON.stringify({game: S.game, choice: S.choice, bet: S.bet})});
    const d = await r.json();
    await new Promise(res => setTimeout(res, 1600));
    clearInterval(shuffler);
    f.classList.remove("roll");
    if (d.error){
      toast(d.error); setFace(faces, ""); document.getElementById("sub").textContent = "выбери ставку и жми";
      S.busy = false; return;
    }
    setFace(g.id === "dice" ? ["", "⚀","⚁","⚂","⚃","⚄","⚅"][d.value] : String(d.value),
            d.won ? "win" : "lose");
    const net = d.delta != null ? d.delta : d.payout - d.bet;
    document.getElementById("val").textContent = d.won
      ? "ВЫИГРЫШ  +" + money(net) : "ПРОИГРЫШ  −" + money(Math.abs(net));
    document.getElementById("val").className = "val " + (d.won ? "win" : "lose");
    document.getElementById("sub").textContent = "Выпало " + d.value + " · ставка «" + d.choice_label + "»";
    S.data.me.balance = d.balance; S.data.me.left = d.left;
    if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred(d.won ? "success" : "error");
  }catch(e){
    clearInterval(shuffler); f.classList.remove("roll"); toast("Связь потерялась");
  }
  S.busy = false; render();
}
document.getElementById("betSet").onclick = () => {
  const v = parseInt(document.getElementById("betInput").value, 10);
  const lim = S.data.limits;
  if (!v || v < lim.min || v > lim.max){ toast("Ставка от " + money(lim.min) + " до " + money(lim.max)); return; }
  S.bet = v; render();
};
document.getElementById("spin").onclick = spin;
if(tg){ tg.ready(); tg.expand(); }
(async () => {
  try{
    const r = await fetch("/api/casino", {headers});
    const d = await r.json();
    if (d.error){ toast(d.error); return; }
    S.data = d; S.game = d.games[0].id; S.choice = d.games[0].choices[0].id;
    S.bet = Math.min(500, d.limits.max);
    render();
  }catch(e){ toast("Не смог загрузить"); }
})();
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# Рулетка: настоящее колесо, шарик и стол
# --------------------------------------------------------------------------- #

# Европейское колесо: порядок лунок как на реальном столе.
ROULETTE_ORDER: tuple[int, ...] = (
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5,
    24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26,
)
ROULETTE_RED: frozenset[int] = frozenset(
    {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
)

ROULETTE_BETS: dict[str, dict[str, Any]] = {
    "red": {"title": "Красное", "mult": 2, "tone": "red"},
    "black": {"title": "Чёрное", "mult": 2, "tone": "black"},
    "green": {"title": "Зелёное", "mult": 5, "tone": "green"},
    "col1": {"title": "1-й столбик", "mult": 3, "tone": "col"},
    "col2": {"title": "2-й столбик", "mult": 3, "tone": "col"},
    "col3": {"title": "3-й столбик", "mult": 3, "tone": "col"},
}


def roulette_color(number: int) -> str:
    if int(number) == 0:
        return "green"
    return "red" if int(number) in ROULETTE_RED else "black"


def roulette_wins(kind: str, number: int) -> bool:
    number = int(number)
    if kind == "green":
        return number == 0
    if number == 0:
        return False
    if kind == "red":
        return number in ROULETTE_RED
    if kind == "black":
        return number not in ROULETTE_RED
    if kind == "col1":
        return number % 3 == 1
    if kind == "col2":
        return number % 3 == 2
    if kind == "col3":
        return number % 3 == 0
    return False


@router.get("/api/roulette_table")
async def api_roulette_table(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    user_id = int(user["id"])
    left = await state.db.casino_left(user_id, roulette_day_key(), casino.SPINS_PER_DAY)
    return JSONResponse(
        {
            "me": {
                "balance": await state.market.balance(user_id),
                "left": left,
                "cap": casino.SPINS_PER_DAY,
            },
            "limits": {"min": casino.MIN_BET, "max": casino.MAX_BET},
            "order": list(ROULETTE_ORDER),
            "red": sorted(ROULETTE_RED),
            "bets": [
                {"id": key, **value} for key, value in ROULETTE_BETS.items()
            ],
        }
    )


@router.post("/api/roulette_table/spin")
async def api_roulette_table_spin(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    user_id = int(user["id"])
    body = await request.json()
    kind = str(body.get("bet_type", ""))
    try:
        bet = int(body.get("bet", 0))
    except (TypeError, ValueError):
        return JSONResponse({"error": "Не понял ставку"}, status_code=400)

    if kind not in ROULETTE_BETS:
        return JSONResponse({"error": "Не понял, на что ставим"}, status_code=400)
    if not casino.MIN_BET <= bet <= casino.MAX_BET:
        return JSONResponse(
            {"error": f"Ставка от {casino.MIN_BET} до {casino.MAX_BET} очков"},
            status_code=400,
        )
    balance = await state.market.balance(user_id)
    if balance < bet:
        return JSONResponse(
            {"error": f"Не хватает очков: ставишь {bet}, у тебя {balance}"},
            status_code=400,
        )

    left = await state.db.claim_casino(user_id, roulette_day_key(), casino.SPINS_PER_DAY)
    if left is None:
        return JSONResponse({"error": "Крутки на сегодня кончились"}, status_code=400)

    number = random.randint(0, 36)
    won = roulette_wins(kind, number)
    mult = int(ROULETTE_BETS[kind]["mult"])
    payout = bet * mult if won else 0
    repo = CasinoRepo(state.db, state.market)
    try:
        async with state.db.pool.acquire() as con:
            async with con.transaction():
                # Тот же расчёт, что и в текстовом казино: баланс, опыт, журнал.
                new_balance = await repo._settle_points(  # noqa: SLF001
                    con,
                    user_id,
                    bet,
                    payout,
                    color=kind,
                    rolled=str(number),
                    won=won,
                    outcome=kind,
                )
    except Exception as error:  # noqa: BLE001
        return JSONResponse({"error": str(error)}, status_code=400)

    return JSONResponse(
        {
            "ok": True,
            "number": number,
            "color": roulette_color(number),
            "won": won,
            "mult": mult,
            "bet": bet,
            "payout": payout,
            "delta": payout - bet,
            "kind": kind,
            "title": str(ROULETTE_BETS[kind]["title"]),
            "balance": int(new_balance),
            "left": await state.db.casino_left(
                user_id, roulette_day_key(), casino.SPINS_PER_DAY
            ),
        }
    )


@router.get("/roulette_table", response_class=HTMLResponse)
async def roulette_table_page() -> HTMLResponse:
    return HTMLResponse(inject(ROULETTE_TABLE_PAGE))


ROULETTE_TABLE_PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<title>Северо-Юг · Рулетка</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{--red:#c0392b;--black:#17181c;--green:#1e8a4c;--up:#3fae6a;--down:#d8434a}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0;overscroll-behavior:none}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg);color:var(--ink);min-height:100vh;padding:14px 0 26px}
.wrap{max-width:520px;margin:0 auto;padding:0 14px}
.head{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.head .b{background:var(--panel);border:1px solid var(--line);border-radius:999px;
  padding:8px 14px;font-size:13px;font-weight:800}
.head .b.bal{color:var(--acc2)}

.stage{display:flex;justify-content:center;margin:6px 0 10px}
.rw{position:relative;width:330px;height:330px;max-width:88vw;max-height:88vw;
  border-radius:50%;padding:11px;
  background:linear-gradient(160deg,#3a2d1e,#1a1410 55%,#2a2016);
  box-shadow:0 18px 44px rgba(0,0,0,.55),inset 0 1px 0 rgba(255,255,255,.09)}
.wheel{position:absolute;inset:11px;border-radius:50%;
  transition:transform 6.4s cubic-bezier(.08,.6,.03,1);
  box-shadow:inset 0 0 0 4px #241c14,inset 0 0 34px rgba(0,0,0,.7)}
.num{position:absolute;top:50%;left:50%;width:18px;height:18px;margin:-9px 0 0 -9px;
  font-size:9.5px;font-weight:900;color:#fff;display:flex;align-items:center;justify-content:center;
  text-shadow:0 1px 2px rgba(0,0,0,.8)}
.ballwrap{position:absolute;inset:11px;pointer-events:none;
  transition:transform 6.9s cubic-bezier(.11,.55,.05,1);z-index:6}
.ball{position:absolute;top:3px;left:50%;width:17px;height:17px;margin-left:-8.5px;border-radius:50%;
  background:radial-gradient(circle at 34% 28%,#ffffff,#c3c8d0 60%,#8b9099);
  box-shadow:0 3px 9px rgba(0,0,0,.75),inset -2px -2px 4px rgba(0,0,0,.25)}
.hub{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
  width:36%;height:36%;border-radius:50%;z-index:5;
  background:radial-gradient(circle at 50% 26%,var(--panel2),var(--panel));
  border:1px solid var(--line);display:flex;flex-direction:column;
  align-items:center;justify-content:center;gap:2px;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.07),0 8px 22px rgba(0,0,0,.5)}
.hub .n{font-size:36px;font-weight:900;letter-spacing:-1.5px;line-height:1}
.hub .c{font-size:10px;letter-spacing:1.4px;text-transform:uppercase;font-weight:800;color:var(--muted)}

.res{text-align:center;font-size:15px;font-weight:900;min-height:22px;letter-spacing:.3px}
.res.win{color:var(--up)} .res.lose{color:var(--down)}
.prev{display:flex;gap:5px;overflow-x:auto;justify-content:flex-start;margin:9px 0 4px;
  scrollbar-width:none;min-height:26px}
.prev::-webkit-scrollbar{display:none}
.prev b{flex:0 0 auto;width:26px;height:26px;border-radius:8px;display:flex;align-items:center;
  justify-content:center;font-size:11px;font-weight:900;color:#fff}

.block{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px;margin-bottom:11px}
.block .t{font-size:10.5px;letter-spacing:1.3px;text-transform:uppercase;color:var(--muted);font-weight:800;margin-bottom:9px}
.bets{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}
.ch{border:1px solid var(--line);background:transparent;color:var(--ink);border-radius:11px;
  padding:12px 6px;font-size:13px;font-weight:800;line-height:1.25}
.ch small{display:block;font-size:10px;font-weight:700;opacity:.7;margin-top:2px}
.ch.on{border-color:var(--acc);background:var(--panel2);box-shadow:0 0 0 1px var(--acc) inset}
.ch.r{color:#ef6a5a} .ch.b{color:#cfd4dc} .ch.g{color:#4fc98a}
.bets4{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}
.bt{border:1px solid var(--line);background:transparent;color:var(--muted);border-radius:11px;
  padding:11px 4px;font-size:13px;font-weight:800}
.bt.on{background:var(--acc);color:var(--acc-ink);border-color:transparent}
.custom{display:flex;gap:7px;margin-top:8px}
.custom input{flex:1;background:var(--panel2);border:1px solid var(--line);border-radius:11px;
  color:var(--ink);padding:11px 13px;font-size:15px;font-weight:800;font-family:inherit}
.custom button{border:1px solid var(--line);background:transparent;color:var(--muted);
  border-radius:11px;padding:0 16px;font-size:13px;font-weight:800}
.go{width:100%;border:0;border-radius:15px;padding:18px;font-size:17px;font-weight:900;
  letter-spacing:1px;color:var(--acc-ink);background:var(--acc)}
.go[disabled]{background:var(--panel2);color:var(--muted)}
#toast{position:fixed;left:14px;right:14px;bottom:16px;background:var(--panel2);color:var(--ink);
  border:1px solid var(--line);border-radius:12px;padding:13px 15px;font-size:13px;
  transform:translateY(220%);transition:.25s;z-index:30}
#toast.on{transform:translateY(0)}
</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <div class="b bal" id="bal">…</div>
    <div class="b" id="spins">…</div>
  </div>

  <div class="stage">
    <div class="rw">
      <div class="wheel" id="wheel"></div>
      <div class="ballwrap" id="ballwrap"><span class="ball"></span></div>
      <div class="hub"><div class="n" id="hubNum">—</div><div class="c" id="hubCol">крути</div></div>
    </div>
  </div>

  <div class="res" id="res">Выбери ставку и крути</div>
  <div class="prev" id="prev"></div>

  <div class="block">
    <div class="t">На что ставим</div>
    <div class="bets" id="bets"></div>
  </div>

  <div class="block">
    <div class="t">Ставка</div>
    <div class="bets4" id="bets4"></div>
    <div class="custom">
      <input id="betInput" type="number" inputmode="numeric" placeholder="своя сумма">
      <button id="betSet">ОК</button>
    </div>
  </div>

  <button class="go" id="go" disabled>КРУТИТЬ</button>
</div>
<div id="toast"></div>
<script>
const tg = window.Telegram ? window.Telegram.WebApp : null;
const headers = {"X-Telegram-Init-Data": tg ? tg.initData : "", "Content-Type": "application/json"};
const PRESETS = [100, 500, 1000, 5000];
const TONE = {green: "#1e8a4c", red: "#c0392b", black: "#17181c"};
let S = {data: null, kind: "red", bet: 500, busy: false, rot: 0, ballRot: 0, last: []};

function esc(s){ return String(s).replace(/[<>&]/g, c => ({"<":"&lt;",">":"&gt;","&":"&amp;"}[c])); }
function money(n){ return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, " "); }
function toast(t){
  const el = document.getElementById("toast");
  el.textContent = t; el.className = "on";
  clearTimeout(el._t); el._t = setTimeout(() => el.className = "", 3000);
}
function colorOf(n, red){ return n === 0 ? "green" : (red.indexOf(n) >= 0 ? "red" : "black"); }

// Колесо: conic-gradient по порядку лунок + подписи чисел
function buildWheel(){
  const order = S.data.order, red = S.data.red;
  const step = 360 / order.length;
  const stops = order.map((n, i) =>
    TONE[colorOf(n, red)] + " " + (i * step).toFixed(3) + "deg " + ((i + 1) * step).toFixed(3) + "deg");
  const w = document.getElementById("wheel");
  w.style.background = "conic-gradient(from 0deg, " + stops.join(",") + ")";
  w.innerHTML = order.map((n, i) => {
    const a = i * step + step / 2;
    return '<span class="num" style="transform:rotate(' + a + 'deg) translateY(-118px) rotate(' +
      (-a) + 'deg)">' + n + '</span>';
  }).join("");
}
function render(){
  const d = S.data;
  document.getElementById("bal").textContent = "Баланс $ " + money(d.me.balance);
  document.getElementById("spins").textContent = "Круток " + d.me.left + "/" + d.me.cap;
  document.getElementById("bets").innerHTML = d.bets.map(b =>
    '<button class="ch ' + (b.tone === "red" ? "r" : b.tone === "black" ? "b" : b.tone === "green" ? "g" : "") +
    (b.id === S.kind ? " on" : "") + '" data-k="' + b.id + '">' + esc(b.title) +
    '<small>×' + b.mult + '</small></button>').join("");
  document.getElementById("bets4").innerHTML = PRESETS.map(b =>
    '<button class="bt' + (S.bet === b ? " on" : "") + '" data-b="' + b + '">' + money(b) + '</button>').join("");
  document.getElementById("go").disabled = S.busy;
  document.querySelectorAll("[data-k]").forEach(el => el.onclick = () => { S.kind = el.dataset.k; render(); });
  document.querySelectorAll("[data-b]").forEach(el => el.onclick = () => {
    S.bet = +el.dataset.b; document.getElementById("betInput").value = ""; render();
  });
  document.getElementById("prev").innerHTML = S.last.map(n => {
    const c = colorOf(n, S.data.red);
    return '<b style="background:' + TONE[c] + ';border:1px solid rgba(255,255,255,.15)">' + n + '</b>';
  }).join("");
}
function spinTo(index){
  const count = S.data.order.length;
  const step = 360 / count;
  const target = -(index * step + step / 2) + (Math.random() - 0.5) * step * 0.45;
  const need = (((target - (S.rot % 360)) % 360) + 360) % 360;
  S.rot += 360 * 6 + need;
  S.ballRot -= 360 * 11;
  document.getElementById("wheel").style.transform = "rotate(" + S.rot + "deg)";
  document.getElementById("ballwrap").style.transform = "rotate(" + S.ballRot + "deg)";
}
async function spin(){
  if (S.busy) return;
  S.busy = true; render();
  document.getElementById("res").textContent = "Шарик пошёл…";
  document.getElementById("res").className = "res";
  try{
    const r = await fetch("/api/roulette_table/spin", {method:"POST", headers,
      body: JSON.stringify({bet_type: S.kind, bet: S.bet})});
    const d = await r.json();
    if (d.error){ toast(d.error); S.busy = false; render(); return; }
    const index = S.data.order.indexOf(d.number);
    spinTo(index < 0 ? 0 : index);
    if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("medium");
    await new Promise(res => setTimeout(res, 7000));
    document.getElementById("hubNum").textContent = d.number;
    document.getElementById("hubCol").textContent = d.color === "red" ? "красное"
      : (d.color === "black" ? "чёрное" : "зелёное");
    const net = d.delta != null ? d.delta : d.payout - d.bet;
    document.getElementById("res").textContent = d.won
      ? "ВЫИГРЫШ +" + money(net) + " · " + d.title
      : "ПРОИГРЫШ −" + money(Math.abs(net)) + " · " + d.title;
    document.getElementById("res").className = "res " + (d.won ? "win" : "lose");
    S.data.me.balance = d.balance; S.data.me.left = d.left;
    S.last = [d.number].concat(S.last).slice(0, 14);
    if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred(d.won ? "success" : "error");
  }catch(e){
    toast("Связь потерялась");
  }
  S.busy = false; render();
}
document.getElementById("go").onclick = spin;
document.getElementById("betSet").onclick = () => {
  const v = parseInt(document.getElementById("betInput").value, 10);
  const lim = S.data.limits;
  if (!v || v < lim.min || v > lim.max){ toast("Ставка от " + money(lim.min) + " до " + money(lim.max)); return; }
  S.bet = v; render();
};
if(tg){ tg.ready(); tg.expand(); }
(async () => {
  try{
    const r = await fetch("/api/roulette_table", {headers});
    const d = await r.json();
    if (d.error){ toast(d.error); return; }
    S.data = d; buildWheel(); render();
  }catch(e){ toast("Не смог загрузить"); }
})();
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# Юга-кликер
# --------------------------------------------------------------------------- #


def _yugi_payload(state: dict[str, Any]) -> dict[str, Any]:
    buildings = state["buildings"]
    ups = state["upgrades"]
    return {
        "balance": round(float(state["balance"]), 2),
        "total": round(float(state["total"]), 2),
        "taps": int(state["taps"]),
        "cases": int(state["cases"]),
        "per_second": round(yugi.per_second(buildings, ups), 2),
        "per_tap": round(yugi.tap_power(ups), 2),
        "cap": yugi.MAX_TOTAL,
        "left": round(yugi.left_to_earn(state["total"]), 2),
        "rate": yugi.CASE_PRICE,
        "buildings": [
            {
                "id": b["id"],
                "name": b["name"],
                "emoji": b["emoji"],
                "note": b["note"],
                "count": int(buildings.get(b["id"], 0)),
                "prod": b["prod"],
                "cost": round(yugi.building_cost(b, buildings.get(b["id"], 0))),
            }
            for b in yugi.BUILDINGS
        ],
        "upgrades": [
            {
                "id": u["id"],
                "name": u["name"],
                "emoji": u["emoji"],
                "note": u["note"],
                "cost": u["cost"],
                "owned": u["id"] in ups,
            }
            for u in yugi.UPGRADES
        ],
    }


async def _yugi_ready(request: Request):
    state = request.app.state
    user = await _player(request)
    user_id = int(user["id"])
    await state.db.ensure_player(user_id, user.get("username"), user.get("first_name"))
    return state, user_id


@router.get("/api/yugi")
async def api_yugi(request: Request) -> JSONResponse:
    try:
        state, user_id = await _yugi_ready(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)
    return await _yugi_extended(state, user_id)


async def _yugi_state(state: Any, user_id: int) -> dict:
    """Полное состояние кликера: тапы, фишки, древо, апгрейды, печенька.

    Раньше его собирал только GET /api/yugi, а tap/buy/case отдавали
    урезанный payload — страница подменяла им состояние, и древо с фишками
    пропадали после первого же действия.
    """
    payload = _yugi_payload(await state.db.yugi_load(user_id))
    payload["chips"] = int(await state.db.yugi_chips_count(user_id))
    tree = await state.db.yugi_tree(user_id)
    payload["tree"] = tree
    payload["tree_pool"] = [
        {
            "id": t["id"],
            "name": t["name"],
            "emoji": t["emoji"],
            "cost": t["cost"],
            "pct": t.get("pct", 0),
            "group": t.get("group", ""),
            "owned": t["id"] in tree,
        }
        for t in yugi.TREE
    ]
    payload["upgrades_pool"] = [
        {
            "id": u["id"],
            "name": u["name"],
            "emoji": u["emoji"],
            "cost": u["cost"],
            "note": u.get("note", ""),
            "owned": u["id"] in payload.get("upgrades", []),
        }
        for u in yugi.UPGRADES
    ]
    payload["golden"] = await state.db.yugi_golden_tick(user_id)
    return payload


async def _yugi_extended(state: Any, user_id: int) -> JSONResponse:
    return JSONResponse(await _yugi_state(state, user_id))


@router.post("/api/yugi/ascend")
async def api_yugi_ascend(request: Request) -> JSONResponse:
    try:
        state, user_id = await _yugi_ready(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)
    res = await state.db.yugi_ascend(user_id)
    if res is None:
        return JSONResponse({"error": "Нужно больше Югов за всё время"}, status_code=400)
    return JSONResponse({"ok": True, **res})


@router.post("/api/yugi/tree")
async def api_yugi_tree(request: Request) -> JSONResponse:
    try:
        state, user_id = await _yugi_ready(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)
    body = await request.json()
    node = str(body.get("id", ""))
    spent = await state.db.yugi_buy_tree(user_id, node)
    if spent is None:
        return JSONResponse({"error": "Не хватает фишек"}, status_code=400)
    payload = await _yugi_state(state, user_id)
    payload["spent"] = spent
    return JSONResponse(payload)


@router.post("/api/yugi/golden")
async def api_yugi_golden(request: Request) -> JSONResponse:
    try:
        state, user_id = await _yugi_ready(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)
    res = await state.db.yugi_golden_catch(user_id)
    if res is None:
        return JSONResponse({"error": "Печенька уже улетела"}, status_code=400)
    return JSONResponse({"ok": True, **res})


@router.post("/api/yugi/tap")
async def api_yugi_tap(request: Request) -> JSONResponse:
    try:
        state, user_id = await _yugi_ready(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    body = await request.json()
    try:
        count = int(body.get("count", 1))
    except (TypeError, ValueError):
        count = 1
    count = max(1, min(300, count))

    # Всё внутри одной транзакции: параллельный запрос не затрёт начисления.
    data = await state.db.yugi_tap(user_id, count)
    if int(data.get("dropped", 0)) >= yugi.FLAG_FROM:
        with contextlib.suppress(Exception):
            await state.db.yugi_flag(user_id, count, int(data.get("accepted", 0)))
    payload = await _yugi_state(state, user_id)
    payload["accepted"] = int(data.get("accepted", 0))
    payload["dropped"] = int(data.get("dropped", 0))
    return JSONResponse(payload)


@router.post("/api/yugi/buy")
async def api_yugi_buy(request: Request) -> JSONResponse:
    try:
        state, user_id = await _yugi_ready(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    body = await request.json()
    kind = str(body.get("kind", ""))
    target = str(body.get("id", ""))
    data = await state.db.yugi_load(user_id)

    if kind not in ("building", "upgrade"):
        return JSONResponse({"error": "Не понял, что покупаем"}, status_code=400)
    if kind == "building" and target not in yugi.BUILDINGS_BY_ID:
        return JSONResponse({"error": "Нет такой постройки"}, status_code=400)
    if kind == "upgrade" and target not in yugi.UPGRADES_BY_ID:
        return JSONResponse({"error": "Нет такого улучшения"}, status_code=400)
    if kind == "upgrade" and target in data["upgrades"]:
        return JSONResponse({"error": "Уже куплено"}, status_code=400)

    bought, cost = await state.db.yugi_spend(
        user_id, building=target if kind == "building" else "",
        upgrade=target if kind == "upgrade" else "",
    )
    if bought is None:
        return JSONResponse({"error": "Не хватает Югов"}, status_code=400)
    return JSONResponse(await _yugi_state(state, user_id))


@router.post("/api/yugi/case")
async def api_yugi_case(request: Request) -> JSONResponse:
    try:
        state, user_id = await _yugi_ready(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    body = await request.json()
    try:
        count = int(body.get("count", 1))
    except (TypeError, ValueError):
        count = 1
    count = max(1, min(150, count))

    cost = yugi.CASE_PRICE * count
    data = await state.db.yugi_buy_cases(user_id, count, cost)
    if data is None:
        return JSONResponse({"error": "Не хватает Югов"}, status_code=400)
    payload = await _yugi_state(state, user_id)
    payload["bought"] = count
    return JSONResponse(payload)


@router.get("/yugi", response_class=HTMLResponse)
async def yugi_app() -> HTMLResponse:
    return HTMLResponse(inject(YUGI_PAGE))
YUGI_PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<title>Северо-Юг · Юга-кликер</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0;overscroll-behavior:none}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg);color:var(--ink);min-height:100vh;padding-bottom:22px}
.wrap{max-width:520px;margin:0 auto;padding:14px}

.hero{text-align:center;padding:6px 0 4px}
.hero .b{font-size:40px;font-weight:900;letter-spacing:-1.6px;line-height:1.05;
  transition:transform .1s}
.hero .b.pop{transform:scale(1.06)}
.hero .u{font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);
  font-weight:800;margin-top:3px}
.hero .s{font-size:13.5px;font-weight:800;color:var(--acc2);margin-top:7px}

.tapzone{position:relative;display:flex;justify-content:center;margin:14px 0 8px;height:230px}
body .tapbtn{width:210px;height:210px;border-radius:50%!important;border:0!important;
  background:radial-gradient(circle at 50% 32%,var(--acc2),var(--acc) 62%,color-mix(in srgb,var(--acc) 70%,#000) 100%)!important;
  color:var(--acc-ink)!important;box-shadow:0 14px 34px color-mix(in srgb,var(--acc) 34%,transparent),
  inset 0 -6px 0 rgba(0,0,0,.18),inset 0 3px 0 rgba(255,255,255,.28)!important;
  display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;
  transition:transform .09s cubic-bezier(.2,.8,.3,1)}
body .tapbtn:active{transform:scale(.93)!important}
body .tapbtn small{font-size:11px;font-weight:800;letter-spacing:2.4px;opacity:.75}
body .tapbtn b{font-size:56px;line-height:1;font-weight:900;letter-spacing:-2px}
.fly{position:absolute;pointer-events:none;font-size:19px;font-weight:900;color:var(--acc2);
  animation:fly 1s ease-out forwards;z-index:6}
@keyframes fly{0%{opacity:1;transform:translateY(0) scale(1)}
  100%{opacity:0;transform:translateY(-92px) scale(1.3)}}

.capwrap{margin:6px 0 4px}
.capbar{height:8px;background:var(--panel2);border-radius:99px;overflow:hidden}
.capbar i{display:block;height:100%;width:0;border-radius:99px;
  background:linear-gradient(90deg,var(--acc),var(--acc2));transition:width .4s ease}
.captext{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);
  margin-top:6px;font-weight:700}

.tabs{display:flex;gap:7px;margin:14px 0 10px}
.tab{flex:1;border:1px solid var(--line);background:var(--panel);color:var(--muted);
  border-radius:12px;padding:12px 4px;font-size:13px;font-weight:800}
.tab.on{background:var(--acc);color:var(--acc-ink);border-color:transparent}

.row{display:flex;align-items:center;gap:11px;background:var(--panel);border:1px solid var(--line);
  border-radius:14px;padding:11px 12px;margin-bottom:8px}
.row .ic{width:42px;height:42px;flex:0 0 auto;border-radius:12px;background:var(--panel2);
  display:flex;align-items:center;justify-content:center;font-size:21px}
.row .mid{flex:1;min-width:0}
.row .nm{font-size:14.5px;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row .nt{font-size:11.5px;color:var(--muted);margin-top:2px}
.row .cnt{font-size:11px;color:var(--acc2);font-weight:800}
.row button{flex:0 0 auto;border:1px solid var(--line)!important;background:transparent!important;
  color:var(--ink)!important;border-radius:11px!important;padding:11px 13px!important;
  font-size:12.5px!important;font-weight:800!important;box-shadow:none!important;min-width:104px}
.row button.can{background:var(--acc)!important;color:var(--acc-ink)!important;border-color:transparent!important}
.row button[disabled]{color:var(--muted)!important;border-color:var(--line)!important}
.row button small{display:block;font-size:10px;opacity:.85;font-weight:700;margin-top:2px}
.own{font-size:12px;font-weight:800;color:var(--up, #3fae6a)}
.ex{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;text-align:center}
.ex .t{font-size:11px;letter-spacing:1.4px;text-transform:uppercase;color:var(--muted);font-weight:800}
.ex .v{font-size:26px;font-weight:900;margin:8px 0 4px}
.ex .s{font-size:12.5px;color:var(--muted);margin-bottom:12px}
.ex button{width:100%;border:0;border-radius:13px;padding:15px;font-size:15px;font-weight:900;
  background:var(--acc);color:var(--acc-ink)}
.ex button[disabled]{background:var(--panel2);color:var(--muted)}
#toast{position:fixed;left:14px;right:14px;bottom:16px;background:var(--panel2);color:var(--ink);
  border:1px solid var(--line);border-radius:12px;padding:13px 15px;font-size:13px;
  transform:translateY(220%);transition:.25s;z-index:30}
#toast.on{transform:translateY(0)}
.apps{display:flex;gap:6px;margin:0 0 12px;background:var(--panel);
  border:1px solid var(--line);border-radius:999px;padding:4px}
.apps a{flex:1;text-align:center;text-decoration:none;color:var(--muted);
  font-weight:800;font-size:12px;padding:9px 4px;border-radius:999px;white-space:nowrap}
.apps a.on{background:var(--acc);color:var(--acc-ink)}
</style>
</head>
<body>
<div class="wrap">
  <nav class="apps">
    <a class="on" href="/yugi">🍁 Кликер</a>
    <a href="/proto_dungeon">🗡 Подземелье</a>
    <a href="/quests">📜 Задания</a>
  </nav>

  <div class="hero">
    <div class="b" id="bal">0</div>
    <div class="u">Югов</div>
    <div class="s" id="perSec">+0 в секунду</div>
  </div>

  <div class="tapzone" id="tapzone">
    <button class="tapbtn" id="tap">
      <small>ЮГА</small>
      <b>🍁</b>
      <small id="perTap">+1 за тап</small>
    </button>
  </div>

  <div style="display:flex;gap:8px;margin:10px 0">
    <div style="flex:1;background:var(--panel);border:1px solid var(--line);
      border-radius:11px;padding:10px 13px;font-size:13px;font-weight:800;
      color:var(--muted)">💠 <span id="chips">0</span> фишек</div>
    <button id="asc" style="border:0;border-radius:11px;padding:10px 16px;
      font-size:13px;font-weight:900;background:var(--acc);color:var(--acc-ink);
      font-family:inherit">Вознестись</button>
  </div>

  <div class="capwrap">
    <div class="capbar"><i id="capFill"></i></div>
    <div class="captext"><span id="capLeft">…</span><span id="capMax">…</span></div>
  </div>

  <div class="tabs" id="tabs"></div>
  <div id="list"></div>
</div>
<div id="toast"></div>
<script>
const tg = window.Telegram ? window.Telegram.WebApp : null;
const headers = {"X-Telegram-Init-Data": tg ? tg.initData : "", "Content-Type": "application/json"};
let S = {data: null, tab: "building", pending: 0, busy: false, timer: null};

function esc(s){ return String(s).replace(/[<>&]/g, c => ({"<":"&lt;",">":"&gt;","&":"&amp;"}[c])); }
function fmt(v){
  v = Number(v) || 0;
  if (v >= 1e6) return (v / 1e6).toFixed(2) + "M";
  if (v >= 1e3) return (v / 1e3).toFixed(1) + "K";
  return Math.round(v).toLocaleString("ru");
}
function toast(t){
  const el = document.getElementById("toast");
  el.textContent = t; el.className = "on";
  clearTimeout(el._t); el._t = setTimeout(() => el.className = "", 2600);
}
function render(){
  const d = S.data;
  document.getElementById("bal").textContent = fmt(d.balance);
  document.getElementById("perSec").textContent = "+" + fmt(d.per_second) + " в секунду";
  document.getElementById("perTap").textContent = "+" + fmt(d.per_tap) + " за тап";
  const done = Math.min(100, d.total / d.cap * 100);
  document.getElementById("capFill").style.width = done.toFixed(2) + "%";
  if (d.cap > 1e12) {
    document.getElementById("capFill").style.width = "100%";
    document.getElementById("capLeft").textContent = "Без ограничений";
    document.getElementById("capMax").textContent = "кейсов " + d.cases;
  } else {
    document.getElementById("capLeft").textContent = d.left <= 0
      ? "МАКСИМУМ собран"
      : "Осталось " + fmt(d.left) + " Югов";
    document.getElementById("capMax").textContent = "Потолок " + fmt(d.cap) + " · кейсов " + d.cases;
  }
  document.getElementById("chips").textContent = d.chips || 0;
  const ascBtn = document.getElementById("asc");
  if (ascBtn && !ascBtn._wired) {
    ascBtn._wired = 1;
    ascBtn.onclick = async () => {
      const r = await post("/api/yugi/ascend", {});
      if (r && r.error) { toast(r.error); return; }
      if (r && r.ok) { toast("Вознесение! +" + r.gain + " фишек"); await load(); }
    };
  }
  const tabs = [["building", "Здания"], ["upgrade", "Улучшения"], ["tree", "🌳 Древо"], ["exchange", "Обмен"]];
  document.getElementById("tabs").innerHTML = tabs.map(t =>
    '<button class="tab' + (S.tab === t[0] ? " on" : "") + '" data-t="' + t[0] + '">' + t[1] + '</button>').join("");
  document.querySelectorAll("[data-t]").forEach(el => el.onclick = () => { S.tab = el.dataset.t; render(); });
  drawList();
}
function drawList(){
  const d = S.data, box = document.getElementById("list");
  if (S.tab === "tree"){
    const pool = d.tree_pool || [];
    const groups = {};
    pool.forEach(t => { (groups[t.group] = groups[t.group] || []).push(t); });
    box.innerHTML = Object.keys(groups).map(g =>
      '<div style="padding:8px 2px 4px;font-size:11px;letter-spacing:1px;' +
      'text-transform:uppercase;color:var(--muted);font-weight:800">' + g + '</div>' +
      groups[g].map(t =>
        '<div class="item' + (t.owned ? " has" : "") + '" data-tree="' + t.id + '"' +
        (t.owned ? "" : ' style="opacity:' + (d.chips >= t.cost ? 1 : 0.45) + '"') + '>' +
        '<div class="ico">' + t.emoji + '</div>' +
        '<div class="mid"><div class="nm">' + t.name + '</div>' +
        '<div class="sub">' + (t.owned ? "куплено" : t.cost + " фишек") + '</div></div>' +
        (t.owned ? '<div class="n">✓</div>' : '') + '</div>').join("")).join("");
    box.querySelectorAll("[data-tree]").forEach(el => el.onclick = async () => {
      const r = await post("/api/yugi/tree", {id: el.dataset.tree});
      if (r && r.error) { toast(r.error); return; }
      if (r && r.tree_pool){ S.data = r; render(); }
      toast("Узел куплен · фишек " + (S.data.chips || 0));
    });
    return;
  }
  if (S.tab === "building"){
    box.innerHTML = d.buildings.map(b =>
      '<div class="row"><div class="ic">' + b.emoji + '</div>' +
      '<div class="mid"><div class="nm">' + esc(b.name) + ' <span class="cnt">×' + b.count + '</span></div>' +
      '<div class="nt">+' + fmt(b.prod) + '/сек · ' + esc(b.note) + '</div></div>' +
      '<button data-k="building" data-i="' + b.id + '" class="' + (d.balance >= b.cost ? "can" : "") + '">' +
      fmt(b.cost) + '<small>Купить</small></button></div>').join("");
  } else if (S.tab === "upgrade"){
    box.innerHTML = d.upgrades.map(u =>
      '<div class="row"><div class="ic">' + u.emoji + '</div>' +
      '<div class="mid"><div class="nm">' + esc(u.name) + '</div>' +
      '<div class="nt">' + esc(u.note) + '</div></div>' +
      (u.owned
        ? '<div class="own">куплено ✓</div>'
        : '<button data-k="upgrade" data-i="' + u.id + '" class="' + (d.balance >= u.cost ? "can" : "") + '">' +
          fmt(u.cost) + '<small>Купить</small></button>') +
      '</div>').join("");
  } else {
    const can = Math.min(1, Math.floor(d.balance / d.rate));
    box.innerHTML = '<div class="ex"><div class="t">Обмен Югов на кейсы</div>' +
      '<div class="v">' + fmt(d.rate) + ' = 1 кейс</div>' +
      '<div class="s">Хватает на ' + can + ' кейс(ов) · у тебя ' + d.cases + '</div>' +
      '<button id="buyCase"' + (can < 1 ? " disabled" : "") + '>Обменять ' + Math.min(can, 10) + ' шт.</button>' +
      '</div>';
    const b = document.getElementById("buyCase");
    if (b) b.onclick = () => buyCase(1);
  }
  document.querySelectorAll("[data-k]").forEach(el => el.onclick = () => buy(el.dataset.k, el.dataset.i));
}
async function post(url, body){
  const r = await fetch(url, {method:"POST", headers, body: JSON.stringify(body || {})});
  return await r.json();
}
async function buy(kind, id){
  if (S.busy) return;
  S.busy = true;
  await flush();          // сначала сохраняем накопленные тапы
  try{
    const d = await post("/api/yugi/buy", {kind, id});
    if (d.error) toast(d.error);
    else {
      S.data = d; render();
      if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("light");
    }
  }catch(e){ toast("Связь потерялась"); }
  S.busy = false;
}
async function buyCase(count){
  if (S.busy) return;
  S.busy = true;
  await flush();
  try{
    const d = await post("/api/yugi/case", {count});
    if (d.error) toast(d.error);
    else { S.data = d; render(); toast("📦 Получено кейсов: " + d.bought); }
  }catch(e){ toast("Связь потерялась"); }
  S.busy = false;
}
function leaf(x, y){
  const el = document.createElement("div");
  el.className = "fly"; el.textContent = "+" + fmt(S.data.per_tap);
  el.style.left = x + "px"; el.style.top = y + "px";
  document.getElementById("tapzone").appendChild(el);
  setTimeout(() => el.remove(), 1000);
}
function maxed(){ return !!S.data && S.data.total >= S.data.cap; }
function addLocal(gain){
  if (!S.data) return 0;
  const room = Math.max(0, S.data.cap - S.data.total);
  const real = Math.min(gain, room);
  if (real <= 0) return 0;
  S.data.balance += real;
  S.data.total += real;
  S.data.left = Math.max(0, S.data.left - real);
  return real;
}
function doTap(ev){
  if (!S.data) return;
  if (maxed()){ toast("Максимум Югов уже собран"); return; }
  const rect = document.getElementById("tapzone").getBoundingClientRect();
  const x = (ev.clientX ? ev.clientX - rect.left : rect.width / 2) - 18;
  const y = (ev.clientY ? ev.clientY - rect.top : rect.height / 2) - 20;
  leaf(x, y);
  S.pending += 1;
  addLocal(S.data.per_tap);
  document.getElementById("bal").textContent = fmt(S.data.balance);
  const b = document.getElementById("bal");
  b.classList.add("pop"); setTimeout(() => b.classList.remove("pop"), 90);
  if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("light");
  clearTimeout(S.timer);
  S.timer = setTimeout(flush, 650);
}
let flushing = false;
async function flush(){
  if (flushing){ clearTimeout(S.timer); S.timer = setTimeout(flush, 300); return; }
  const count = S.pending;
  S.pending = 0;
  if (!count) return;
  flushing = true;
  try{
    const d = await post("/api/yugi/tap", {count});
    if (!d.error){
      S.data = d; render();
      if (d.dropped >= 5) toast("Слишком быстро — часть тапов не зачлась");
    }
  }catch(e){ /* вернём при следующем тапе */ S.pending += count; }
  finally { flushing = false; }
}
document.getElementById("tap").onclick = doTap;
/* ---------- золотая печенька ---------- */
(function(){
  if (!document.body || !document.body.appendChild) return;
  const el = document.createElement("button");
  el.id = "golden";
  el.textContent = "🍪";
  el.title = "Золотая печенька";
  el.hidden = true;
  el.style.cssText =
    "position:fixed;right:18px;bottom:132px;width:76px;height:76px;border:0;" +
    "border-radius:50%;font-size:38px;line-height:1;z-index:40;padding:0;" +
    "background:radial-gradient(circle at 35% 30%,#ffe9a8,#f6b73c);" +
    "box-shadow:0 0 26px #ffd166bb,0 6px 16px #00000055";
  document.body.appendChild(el);

  let until = 0;
  async function refresh(){
    try{
      const r = await fetch("/api/yugi", {headers});
      const d = await r.json();
      if (d.error || !d.golden) return;
      const at = d.golden.until ? Date.parse(d.golden.until) : 0;
      until = d.golden.active ? at : 0;
      el.hidden = !(until > Date.now());
    }catch(e){}
  }

  el.onclick = async function(){
    el.hidden = true;
    try{
      const r = await fetch("/api/yugi/golden", {method: "POST", headers});
      const d = await r.json();
      if (d.error){ toast(d.error); return; }
      if (d.kind === "frenzy") toast("🍪 Безумие: доход x2 на 77 секунд");
      else if (d.kind === "click") toast("🍪 Печенька: клик сильнее на 13 секунд");
      else toast("🍪 Печенька: +" + fmt(d.bonus || 0) + " Югов");
      const rr = await fetch("/api/yugi", {headers});
      const dd = await rr.json();
      if (!dd.error){ S.data = dd; render(); }
    }catch(e){ toast("Не смог поймать"); }
  };

  setInterval(function(){ if (!S.pending || !el.hidden) refresh(); }, 12000);
  setTimeout(refresh, 2500);
})();

if(tg){ tg.ready(); tg.expand(); }
(async () => {
  try{
    const r = await fetch("/api/yugi", {headers});
    const d = await r.json();
    if (d.error){ toast(d.error); return; }
    S.data = d; render();
  }catch(e){ toast("Не смог загрузить"); }
})();
setInterval(() => {
  if (!S.data || S.pending) return;
  if (maxed()){
    // Потолок взят: доход останавливается, и на экране это видно.
    const fill = document.getElementById("capFill");
    if (fill) fill.style.width = "100%";
    const left = document.getElementById("capLeft");
    if (left) left.textContent = "МАКСИМУМ собран";
    return;
  }
  addLocal(S.data.per_second * 2);
  document.getElementById("bal").textContent = fmt(S.data.balance);
}, 2000);
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# Недельный ивент «Звёздочка»
# --------------------------------------------------------------------------- #


def _event_payload(state_row: dict, day: int, quests: list, player: dict, me: dict) -> dict:
    ev = event_week
    claimed = len([q for q in quests if q["claimed"]])
    done_ready = len([q for q in quests if q["done"] and not q["claimed"]])
    return {
        "active": True,
        "day": day,
        "days": ev.DAYS,
        "need": ev.NEED,
        "done": int(player.get("done_count") or 0),
        "claimed": claimed,
        "ready": done_ready,
        "quests": quests,
        "me": me,
        "main": {
            "unlocked": bool(player.get("main_unlocked")),
            "done": bool(player.get("main_done")),
            "drops": int(player.get("main_drops") or 0),
            "roulette": int(player.get("main_roulette") or 0),
            "cases": int(player.get("main_cases") or 0),
            "points": int(player.get("main_points") or 0),
            "need_drops": ev.MAIN_DROPS,
            "need_roulette": ev.MAIN_ROULETTE,
            "need_cases": ev.MAIN_CASES,
            "need_points": ev.MAIN_POINTS,
        },
    }


@router.get("/api/event")
async def api_event(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    user_id = int(user["id"])
    row = await state.db.event_state()
    now = datetime.now(timezone.utc)
    if not row.get("active"):
        return JSONResponse({"active": False})
    if event_week.is_over(row.get("ends_at"), now):
        await state.db.event_stop()
        return JSONResponse({"active": False, "ended": True})

    day = event_week.day_of(row.get("started_at"), now) or 1
    await state.db.event_ensure(user_id, day)
    granted = await state.db.event_grant_daily(user_id, day)
    quests = await state.db.event_quests(user_id)
    player = await state.db.event_player(user_id)
    async with state.db.pool.acquire() as con:  # type: ignore[attr-defined]
        prow = await con.fetchrow(
            "select drop_limit, roulette_limit, bonus_points from players "
            "where user_id = $1",
            user_id,
        )
        cases_have = int(
            await con.fetchval(
                "select count(*) from cases where user_id = $1", user_id
            )
            or 0
        )
    me = {
        "balance": int(prow["bonus_points"]) if prow else 0,
        "drops": int(prow["drop_limit"]) if prow else 0,
        "roulette": int(prow["roulette_limit"]) if prow else 0,
        "cases": cases_have,
        "granted": granted,
    }
    return JSONResponse(_event_payload(row, day, quests, player, me))


@router.post("/api/event/claim")
async def api_event_claim(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    user_id = int(user["id"])
    body = await request.json()
    try:
        quest_id = int(body.get("id", 0))
    except (TypeError, ValueError):
        return JSONResponse({"error": "Не понял квест"}, status_code=400)

    result = await state.db.event_claim(user_id, quest_id)
    if result is None:
        return JSONResponse({"error": "Квест ещё не готов"}, status_code=400)
    reward = result["reward"]
    return JSONResponse(
        {
            "ok": True,
            "reward": reward,
            "reward_text": event_week.reward_text(reward),
            "done": result["done"],
            "unlocked": result["unlocked"],
            "balance": await state.market.balance(user_id),
        }
    )


@router.post("/api/event/contribute")
async def api_event_contribute(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    user_id = int(user["id"])
    body = await request.json()
    try:
        drops = int(body.get("drops", 0))
        roulette = int(body.get("roulette", 0))
        cases = int(body.get("cases", 0))
        points = int(body.get("points", 0))
    except (TypeError, ValueError):
        return JSONResponse({"error": "Не понял, что кладём"}, status_code=400)
    result = await state.db.event_contribute(user_id, drops, roulette, cases, points)
    if result is None:
        return JSONResponse({"error": "Не хватает ресурсов"}, status_code=400)
    return JSONResponse(
        {
            "ok": True,
            "complete": bool(result.get("complete")),
            "main": {
                "drops": int(result["main_drops"]),
                "roulette": int(result["main_roulette"]),
                "cases": int(result["main_cases"]),
                "points": int(result["main_points"]),
            },
            "balance": await state.market.balance(user_id),
        }
    )


@router.get("/event", response_class=HTMLResponse)
async def event_page() -> HTMLResponse:
    return HTMLResponse(inject(EVENT_PAGE))

EVENT_PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<title>Северо-Юг · Событие</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{--up:#3fae6a}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg);color:var(--ink);min-height:100vh;padding-bottom:24px}
.wrap{max-width:520px;margin:0 auto;padding:14px}
.hero{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px;
  position:relative;overflow:hidden;text-align:center}
.hero::before{content:"";position:absolute;inset:-40% -20% auto;height:80%;
  background:radial-gradient(60% 60% at 50% 0%,color-mix(in srgb,var(--acc) 24%,transparent),transparent 70%);
  pointer-events:none}
.hero .star{font-size:44px;line-height:1;animation:tw 3.4s ease-in-out infinite}
@keyframes tw{0%,100%{transform:scale(1) rotate(0);opacity:.92}50%{transform:scale(1.12) rotate(6deg);opacity:1}}
.hero h1{margin:8px 0 4px;font-size:20px}
.hero p{margin:0;font-size:12.5px;color:var(--muted);line-height:1.55}
.bar{height:10px;background:var(--panel2);border-radius:99px;overflow:hidden;margin-top:14px}
.bar i{display:block;height:100%;width:0;border-radius:99px;
  background:linear-gradient(90deg,var(--acc),var(--acc2));transition:width .5s cubic-bezier(.2,.8,.3,1)}
.nums{display:flex;justify-content:space-between;font-size:11.5px;color:var(--muted);margin-top:6px;font-weight:700}
.sect{margin-top:14px;font-size:11px;letter-spacing:1.4px;text-transform:uppercase;
  color:var(--muted);font-weight:800;padding:0 2px 8px}
.q{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px;margin-bottom:8px;
  display:flex;align-items:center;gap:11px}
.q.done{border-color:color-mix(in srgb,var(--up) 55%,var(--line))}
.q .ic{width:38px;height:38px;flex:0 0 auto;border-radius:11px;background:var(--panel2);
  display:flex;align-items:center;justify-content:center;font-size:18px}
.q .mid{flex:1;min-width:0}
.q .t{font-size:13.5px;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.q .p{font-size:11.5px;color:var(--muted);margin-top:2px}
.q .pb{height:4px;background:var(--panel2);border-radius:99px;margin-top:6px;overflow:hidden}
.q .pb i{display:block;height:100%;background:var(--acc);border-radius:99px;transition:width .35s ease}
.q button{flex:0 0 auto;border:1px solid var(--line)!important;background:transparent!important;
  color:var(--muted)!important;border-radius:10px!important;padding:10px 13px!important;
  font-size:12px!important;font-weight:800!important;box-shadow:none!important}
.q button.ready{background:var(--acc)!important;color:var(--acc-ink)!important;border-color:transparent!important}
.main{background:var(--panel);border:1px solid color-mix(in srgb,var(--acc) 40%,var(--line));
  border-radius:16px;padding:14px;margin-top:6px}
.main .row{display:flex;justify-content:space-between;font-size:13px;font-weight:700;padding:5px 0}
.main .row span{color:var(--muted)}
.main .row b{color:var(--acc2)}
.main button{width:100%;margin-top:10px;border:0;border-radius:12px;padding:14px;font-size:14px;
  font-weight:900;background:var(--acc);color:var(--acc-ink)}
.main button[disabled]{background:var(--panel2);color:var(--muted)}
.locked{text-align:center;color:var(--muted);font-size:12.5px;padding:18px;line-height:1.6}
#toast{position:fixed;left:14px;right:14px;bottom:16px;background:var(--panel2);color:var(--ink);
  border:1px solid var(--line);border-radius:12px;padding:13px 15px;font-size:13px;
  transform:translateY(220%);transition:.25s;z-index:30}
#toast.on{transform:translateY(0)}
</style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <div class="star">🌟</div>
    <h1>Звёздочка</h1>
    <p id="story">Звёздочка упала на школьный двор и рассыпалась на осколки.
       Каждый осколок — квест. Собери их и помоги ей вернуться домой.</p>
    <div class="bar"><i id="fill"></i></div>
    <div class="nums"><span id="left">…</span><span id="day">…</span></div>
  </div>
  <div class="sect" id="sect">Квесты дня</div>
  <div id="list"></div>
</div>
<div id="toast"></div>
<script>
const tg = window.Telegram ? window.Telegram.WebApp : null;
const headers = {"X-Telegram-Init-Data": tg ? tg.initData : "", "Content-Type": "application/json"};
let S = {data: null, busy: false};

function esc(s){ return String(s).replace(/[<>&]/g, c => ({"<":"&lt;",">":"&gt;","&":"&amp;"}[c])); }
function money(n){ return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, " "); }
function toast(t){
  const el = document.getElementById("toast");
  el.textContent = t; el.className = "on";
  clearTimeout(el._t); el._t = setTimeout(() => el.className = "", 3200);
}
function render(){
  const d = S.data;
  if (!d || !d.active){
    document.getElementById("story").textContent = "Сейчас событие не идёт. Жди запуска.";
    document.getElementById("sect").textContent = "";
    document.getElementById("list").innerHTML =
      '<div class="locked">Звёздочка ещё спит.<br>Скоро она снова упадёт на школьный двор.</div>';
    return;
  }
  document.getElementById("fill").style.width = Math.min(100, d.done / d.need * 100) + "%";
  document.getElementById("left").textContent = "Собрано " + d.done + " из " + d.need;
  document.getElementById("day").textContent = "День " + d.day + " из " + d.days;
  document.getElementById("sect").textContent = "Квесты дня " + d.day;
  const today = d.quests.filter(q => q.day === d.day && !q.claimed);
  const older = d.quests.filter(q => q.day < d.day && !q.claimed);
  const rows = [];
  today.forEach(q => rows.push(row(q)));
  if (older.length){
    rows.push('<div class="sect">Остались с прошлых дней</div>');
    older.forEach(q => rows.push(row(q)));
  }
  if (!today.length && !older.length){
    rows.push('<div class="locked">Все квесты дня закрыты. Возвращайся завтра — придут новые.</div>');
  }
  if (d.main.unlocked) rows.push(mainBlock(d.main));
  document.getElementById("list").innerHTML = rows.join("");
  document.querySelectorAll("[data-claim]").forEach(b => b.onclick = () => claim(+b.dataset.claim));
  const cb = document.getElementById("contribute");
  if (cb) cb.onclick = contribute;
}
function row(q){
  const pct = Math.min(100, q.progress / q.need * 100);
  return '<div class="q' + (q.done ? " done" : "") + '">' +
    '<div class="ic">' + (q.done ? "✅" : "✦") + '</div>' +
    '<div class="mid"><div class="t">' + esc(q.title) + '</div>' +
    '<div class="p">' + q.progress + " / " + q.need + '</div>' +
    '<div class="pb"><i style="width:' + pct + '%"></i></div></div>' +
    (q.done
      ? '<button class="ready" data-claim="' + q.id + '">Забрать</button>'
      : '<button disabled>ждём</button>') + '</div>';
}
function mainBlock(m){
  const line = (label, have, need) =>
    '<div class="row"><span>' + label + '</span><b>' + money(have) + " / " + money(need) + '</b></div>';
  return '<div class="main"><div class="sect" style="padding:0 0 8px">Главный квест</div>' +
    line("Крутки «Северо-Юг»", m.drops, m.need_drops) +
    line("Крутки рулетки", m.roulette, m.need_roulette) +
    line("Кейсы", m.cases, m.need_cases) +
    line("Очки", m.points, m.need_points) +
    (m.done
      ? '<button disabled>Собрано — награда уже твоя</button>'
      : '<button id="contribute">Положить всё</button>') + '</div>';
}
async function post(url, body){
  const r = await fetch(url, {method:"POST", headers, body: JSON.stringify(body || {})});
  return await r.json();
}
async function claim(id){
  if (S.busy) return;
  S.busy = true;
  try{
    const d = await post("/api/event/claim", {id});
    if (d.error) toast(d.error);
    else {
      toast("Награда: " + d.reward_text + " · собрано " + d.done + "/" + S.data.need);
      if (d.unlocked) toast("Главный квест открыт!");
      if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
      await load();
    }
  }catch(e){ toast("Связь потерялась"); }
  S.busy = false;
}
async function contribute(){
  if (S.busy) return;
  const m = S.data.main, me = S.data.me;
  const body = {
    drops: Math.min(m.need_drops - m.drops, me.drops),
    roulette: Math.min(m.need_roulette - m.roulette, me.roulette),
    cases: Math.min(m.need_cases - m.cases, me.cases),
    points: Math.min(m.need_points - m.points, me.balance),
  };
  S.busy = true;
  try{
    const d = await post("/api/event/contribute", body);
    if (d.error) toast("Не хватает ресурсов");
    else { toast(d.complete ? "Главный квест собран!" : "Положено"); await load(); }
  }catch(e){ toast("Связь потерялась"); }
  S.busy = false;
}
async function load(){
  try{
    const r = await fetch("/api/event", {headers});
    const d = await r.json();
    if (d.error){ toast(d.error); return; }
    S.data = d; render();
  }catch(e){ toast("Не смог загрузить"); }
}
if(tg){ tg.ready(); tg.expand(); }
load();
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# Профили
# --------------------------------------------------------------------------- #


async def _profile_payload(state, user_id: int) -> dict[str, Any]:
    prof = await state.db.profile_get(user_id)
    rewards = await state.db.profile_rewards(user_id)
    tags = await state.db.profile_tags(user_id)
    data = await state.db.player_profile(user_id) or {}
    name = data.get("first_name") or data.get("username") or "игрок"
    xp = int(data.get("xp") or 0)
    return {
        "id": int(user_id),
        "name": name,
        "username": data.get("username") or "",
        "level": levels.level_from_xp(xp),
        "xp": xp,
        "wins": int(data.get("wins") or 0),
        "losses": int(data.get("losses") or 0),
        "cards": int(data.get("unique_cards") or 0),
        "balance": int(data.get("bonus_points") or 0),
        "initial": profiles.initial(str(name)),
        "avatar_color": profiles.avatar_color(str(name)),
        "bio": prof["bio"],
        "status": prof["status"],
        "banner": prof["banner"],
        "banner_css": profiles.banner_css(prof["banner"]),
        "banner_name": profiles.banner_name(prof["banner"]),
        "music": prof["music"],
        "avatar": prof["avatar"],
        "vip": await state.db.vip_active(user_id),
        "rewards": [
            {"id": int(r["id"]), "icon": str(r["icon"]), "text": str(r["text"])}
            for r in rewards
        ],
        "tags": [
            {"key": t, "label": profiles.tag_label(t)} for t in tags
        ],
    }


@router.get("/api/profile")
async def api_profile(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    me = int(user["id"])
    raw = request.query_params.get("u", "")
    target = me
    if raw:
        try:
            target = int(raw)
        except ValueError:
            target = me
    await state.db.ensure_player(target, None, None)
    payload = await _profile_payload(state, target)
    payload["is_me"] = target == me
    payload["banners"] = [
        {"key": k, "name": v["name"], "css": profiles.banner_css(k)}
        for k, v in profiles.BANNERS.items()
    ]
    payload["limits"] = {
        "bio": profiles.MAX_BIO,
        "status": profiles.MAX_STATUS,
        "music": profiles.MAX_MUSIC,
        "avatar": 400,
    }
    return JSONResponse(payload)


@router.get("/api/profile/search")
async def api_profile_search(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)
    query = request.query_params.get("q", "")
    rows = await state.db.profile_find(query)
    return JSONResponse(
        {
            "results": [
                {
                    "id": int(r["user_id"]),
                    "name": r["first_name"] or r["username"] or "игрок",
                    "level": levels.level_from_xp(int(r["xp"] or 0)),
                    "initial": profiles.initial(str(r["first_name"] or r["username"])),
                    "color": profiles.avatar_color(str(r["first_name"] or r["username"])),
                }
                for r in rows
            ]
        }
    )


@router.post("/api/profile/save")
async def api_profile_save(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    user_id = int(user["id"])
    body = await request.json()
    banner = str(body.get("banner", "")) or profiles.DEFAULT_BANNER
    if banner not in profiles.BANNERS:
        banner = profiles.DEFAULT_BANNER
    bio = profiles.clean(body.get("bio"), profiles.MAX_BIO)
    status_text = profiles.clean(body.get("status"), profiles.MAX_STATUS)
    music = profiles.clean(body.get("music"), profiles.MAX_MUSIC)
    avatar = profiles.clean_url(body.get("avatar"))
    await state.db.profile_save(user_id, bio, status_text, banner, music, avatar)
    payload = await _profile_payload(state, user_id)
    payload["is_me"] = True
    return JSONResponse({"ok": True, "profile": payload})


@router.get("/profile", response_class=HTMLResponse)
async def profile_page() -> HTMLResponse:
    return HTMLResponse(inject(PROFILE_PAGE))


PROFILE_PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<title>Северо-Юг · Профиль</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg);color:var(--ink);min-height:100vh;padding-bottom:24px}
.wrap{max-width:520px;margin:0 auto;padding:14px}
.search{display:flex;gap:8px;margin-bottom:12px}
.search input{flex:1;background:var(--panel2);border:1px solid var(--line);border-radius:12px;
  color:var(--ink);padding:12px 14px;font-size:14px;font-family:inherit}
.search button{border:0;border-radius:12px;padding:0 18px;font-size:13px;font-weight:800;
  background:var(--acc);color:var(--acc-ink)}
.res{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px 12px;
  margin-bottom:6px;display:flex;align-items:center;gap:10px}
.res .a{width:34px;height:34px;border-radius:50%;display:flex;align-items:center;
  justify-content:center;font-weight:900;color:#12100e;font-size:15px}
.res .n{flex:1;font-size:13.5px;font-weight:800}
.res .l{font-size:11.5px;color:var(--muted)}

.card{background:var(--panel);border:1px solid var(--line);border-radius:18px;overflow:hidden}
.banner{height:132px;position:relative}
.banner .av{position:absolute;left:16px;bottom:-34px;width:82px;height:82px;border-radius:50%;
  border:4px solid var(--panel);display:flex;align-items:center;justify-content:center;
  font-size:34px;font-weight:900;color:#12100e;box-shadow:0 8px 22px rgba(0,0,0,.4);
  overflow:hidden}
.banner .av img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
/* VIP: золотая рамка с мягким пульсирующим ореолом */
.banner .av.vip{box-shadow:0 0 0 3px #f6c94a,0 0 20px rgba(246,201,74,.55),
  0 8px 22px rgba(0,0,0,.45)}
.banner .av.vip::after{content:"";position:absolute;inset:-8px;border-radius:50%;
  border:2px solid rgba(246,201,74,.5);animation:__vipring 2.8s ease-in-out infinite}
@keyframes __vipring{
  0%,100%{opacity:.3;transform:scale(1)}
  50%{opacity:.85;transform:scale(1.07)}
}
.crown{font-size:15px;filter:drop-shadow(0 0 6px rgba(246,201,74,.7))}
.body{padding:44px 16px 16px}
.nm{font-size:21px;font-weight:900;letter-spacing:-.3px;display:flex;align-items:center;
  gap:7px;flex-wrap:wrap}
.tag{font-size:10.5px;font-weight:800;background:color-mix(in srgb,var(--acc) 20%,var(--panel2));
  color:var(--acc2);border:1px solid color-mix(in srgb,var(--acc) 40%,var(--line));
  border-radius:99px;padding:3px 9px}
.st{font-size:12.5px;color:var(--muted);margin-top:4px}
.bio{font-size:13px;line-height:1.55;margin-top:10px;color:var(--ink)}
.mus{font-size:12.5px;color:var(--acc2);margin-top:8px}
.rew{display:flex;flex-direction:column;gap:5px;margin-top:12px}
.rew div{font-size:12.5px;background:var(--panel2);border:1px solid var(--line);
  border-radius:10px;padding:7px 11px}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:14px}
.stats div{background:var(--panel2);border:1px solid var(--line);border-radius:11px;padding:9px;text-align:center}
.stats b{display:block;font-size:16px;font-weight:900}
.stats span{font-size:10px;color:var(--muted);letter-spacing:.6px;text-transform:uppercase}
.edit{margin-top:16px;border-top:1px solid var(--line);padding-top:14px}
.edit label{display:block;font-size:10.5px;letter-spacing:1.2px;text-transform:uppercase;
  color:var(--muted);font-weight:800;margin:10px 0 6px}
.edit input,.edit textarea{width:100%;background:var(--panel2);border:1px solid var(--line);
  border-radius:11px;color:var(--ink);padding:11px 13px;font-size:13.5px;font-family:inherit;resize:none}
.bans{display:flex;gap:7px;overflow-x:auto;padding-bottom:4px;scrollbar-width:none}
.bans::-webkit-scrollbar{display:none}
.bans button{flex:0 0 auto;width:58px;height:38px;border-radius:10px;border:2px solid transparent}
.bans button.on{border-color:var(--acc)}
.save{width:100%;margin-top:14px;border:0;border-radius:13px;padding:15px;font-size:15px;
  font-weight:900;background:var(--acc);color:var(--acc-ink)}
.empty{text-align:center;color:var(--muted);padding:40px 16px;font-size:13px;line-height:1.6}
#toast{position:fixed;left:14px;right:14px;bottom:16px;background:var(--panel2);color:var(--ink);
  border:1px solid var(--line);border-radius:12px;padding:13px 15px;font-size:13px;
  transform:translateY(220%);transition:.25s;z-index:30}
#toast.on{transform:translateY(0)}
</style>
</head>
<body>
<div class="wrap">
  <div class="search">
    <input id="q" placeholder="Найти игрока по нику…">
    <button id="goBtn">Найти</button>
  </div>
  <div id="results"></div>
  <div id="card"><div class="empty">Загружаю профиль…</div></div>
</div>
<div id="toast"></div>
<script>
const tg = window.Telegram ? window.Telegram.WebApp : null;
const headers = {"X-Telegram-Init-Data": tg ? tg.initData : "", "Content-Type": "application/json"};
let S = {data: null, banner: "sunset", busy: false};

function esc(s){ return String(s == null ? "" : s).replace(/[<>&"]/g, c => ({"<":"&lt;",">":"&gt;","&":"&amp;",'"':"&quot;"}[c])); }
function toast(t){
  const el = document.getElementById("toast");
  el.textContent = t; el.className = "on";
  clearTimeout(el._t); el._t = setTimeout(() => el.className = "", 2800);
}
function cardHtml(d){
  const tags = (d.tags || []).map(t => '<span class="tag">' + esc(t.label) + '</span>').join("");
  const rewards = (d.rewards || []).length
    ? '<div class="rew">' + d.rewards.map(r =>
        '<div>' + esc(r.icon) + " " + esc(r.text) + '</div>').join("") + '</div>'
    : "";
  return '<div class="card">' +
    '<div class="banner" style="background:' + d.banner_css + '">' +
      '<div class="av' + (d.vip ? " vip" : "") + '" style="background:' + d.avatar_color + '">' +
        '<span>' + esc(d.initial) + '</span>' +
        (d.avatar ? '<img src="' + esc(d.avatar) + '" alt="" onerror="this.remove()">' : '') +
      '</div>' +
    '</div>' +
    '<div class="body">' +
      '<div class="nm">' + esc(d.name) + (d.vip ? '<span class="crown">👑</span>' : "") + tags + '</div>' +
      (d.status ? '<div class="st">' + esc(d.status) + '</div>' : '') +
      (d.bio ? '<div class="bio">' + esc(d.bio) + '</div>' : '') +
      (d.music ? '<div class="mus">\uD83C\uDFB5 ' + esc(d.music) + '</div>' : '') +
      rewards +
      '<div class="stats">' +
        '<div><b>' + d.level + '</b><span>уровень</span></div>' +
        '<div><b>' + d.wins + '</b><span>побед</span></div>' +
        '<div><b>' + d.cards + '</b><span>карт</span></div>' +
      '</div>' +
      (d.is_me ? editHtml(d) : '') +
    '</div></div>';
}
function editHtml(d){
  const bans = (d.banners || []).map(b =>
    '<button data-ban="' + b.key + '" class="' + (b.key === S.banner ? "on" : "") +
    '" style="background:' + b.css + '"></button>').join("");
  return '<div class="edit">' +
    '<label>Описание</label>' +
    '<textarea id="fBio" rows="3" maxlength="' + d.limits.bio + '">' + esc(d.bio) + '</textarea>' +
    '<label>Статус</label>' +
    '<input id="fStatus" maxlength="' + d.limits.status + '" value="' + esc(d.status) + '">' +
    '<label>Аватарка — ссылка на картинку</label>' +
    '<input id="fAvatar" maxlength="' + (d.limits.avatar || 400) + '" ' +
      'placeholder="https://…" value="' + esc(d.avatar || "") + '">' +
    '<label>Музыка</label>' +
    '<input id="fMusic" maxlength="' + d.limits.music + '" value="' + esc(d.music) + '">' +
    '<label>Баннер</label><div class="bans">' + bans + '</div>' +
    '<button class="save" id="saveBtn">Сохранить</button></div>';
}
function paint(){
  document.getElementById("card").innerHTML = cardHtml(S.data);
  document.querySelectorAll("[data-ban]").forEach(b => b.onclick = () => {
    S.banner = b.dataset.ban; paint();
  });
  const sb = document.getElementById("saveBtn");
  if (sb) sb.onclick = save;
}
async function save(){
  if (S.busy) return;
  S.busy = true;
  const body = {
    bio: document.getElementById("fBio").value,
    status: document.getElementById("fStatus").value,
    music: document.getElementById("fMusic").value,
    avatar: document.getElementById("fAvatar").value,
    banner: S.banner,
  };
  try{
    const r = await fetch("/api/profile/save", {method:"POST", headers, body: JSON.stringify(body)});
    const d = await r.json();
    if (d.error) toast(d.error);
    else {
      toast("Сохранено");
      if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
      await open(S.data.id);
    }
  }catch(e){ toast("Связь потерялась"); }
  S.busy = false;
}
async function open(id){
  try{
    const url = id ? "/api/profile?u=" + id : "/api/profile";
    const r = await fetch(url, {headers});
    const d = await r.json();
    if (d.error){ toast(d.error); return; }
    S.data = d; S.banner = d.banner; paint();
  }catch(e){ toast("Не смог загрузить"); }
}
async function search(){
  const q = document.getElementById("q").value.trim();
  if (q.length < 2){ toast("Хотя бы две буквы"); return; }
  try{
    const r = await fetch("/api/profile/search?q=" + encodeURIComponent(q), {headers});
    const d = await r.json();
    if (d.error){ toast(d.error); return; }
    const box = document.getElementById("results");
    if (!d.results.length){ box.innerHTML = '<div class="empty">Никого не нашёл</div>'; return; }
    box.innerHTML = d.results.map(u =>
      '<div class="res" data-u="' + u.id + '">' +
      '<div class="a" style="background:' + u.color + '">' + esc(u.initial) + '</div>' +
      '<div class="n">' + esc(u.name) + '</div>' +
      '<div class="l">ур. ' + u.level + '</div></div>').join("");
    document.querySelectorAll("[data-u]").forEach(el => el.onclick = () => {
      document.getElementById("results").innerHTML = "";
      open(+el.dataset.u);
    });
  }catch(e){ toast("Связь потерялась"); }
}
document.getElementById("goBtn").onclick = search;
document.getElementById("q").addEventListener("keydown", e => { if (e.key === "Enter") search(); });
if(tg){ tg.ready(); tg.expand(); }
// ?u=123 — чужой профиль: ссылки из лидерборда и поиска ведут сюда
const startUser = new URLSearchParams(location.search).get("u");
open(startUser ? +startUser : 0);
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# Коллекция — мини-аппка
# --------------------------------------------------------------------------- #


@router.get("/api/collection")
async def api_collection(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    user_id = int(user["id"])
    counts = await state.db.get_collection(user_id)
    cards = []
    for card in cards_sorted_for_user(list(counts)):
        cards.append(
            {
                "id": card.card_id,
                "name": card.display_name,
                "emoji": card.rarity_emoji,
                "rarity": card.rarity,
                "rarity_title": rarity_name(card.rarity),
                "hp": card.hp,
                "atk": card.atk,
                "points": card.points,
                "price": market_price(card),
                "count": int(counts[card.card_id]),
                "image": image_url(card.card_id),
                "ability": card.ability.name,
                "ability_text": describe_ability(card),
                "description": card.description or "",
            }
        )
    upgraded = []
    for row in await state.market.user_inventory(user_id):
        card = get_card(str(row["card_id"]))
        bonus = row.get("bonus") or {}
        upgraded.append(
            {
                "inventory_id": int(row["id"]),
                "id": card.card_id,
                "name": card.display_name,
                "emoji": card.rarity_emoji,
                "rarity_title": rarity_name(card.rarity),
                "price": market_price(card, bonus),
                "image": image_url(card.card_id),
                "bonus": bonus,
            }
        )
    return JSONResponse(
        {
            "cards": cards,
            "upgraded": upgraded,
            "balance": await state.market.balance(user_id),
            "upgrade_price": UPGRADE_PRICE,
            "total": len(cards),
        }
    )


@router.post("/api/collection/upgrade")
async def api_collection_upgrade(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    user_id = int(user["id"])
    body = await request.json()
    card_id = str(body.get("card_id", ""))
    if card_id not in CARDS_BY_ID:
        return JSONResponse({"error": "Такой карты нет."}, status_code=400)
    try:
        outcome = await state.market.upgrade_stack(user_id, card_id)
    except Exception as error:  # noqa: BLE001
        return JSONResponse({"error": str(error)[:160]}, status_code=400)

    items = []
    for slot in ("aura", "background", "effect"):
        item = (outcome.get("items") or {}).get(slot)
        if item is not None:
            items.append(
                {
                    "slot": slot,
                    "name": str(item.name),
                    "summary": str(item.summary),
                }
            )
    return JSONResponse(
        {
            "ok": True,
            "card_id": card_id,
            "items": items,
            "balance": int(outcome["balance"]),
            "inventory_id": int(outcome["inventory_id"]),
        }
    )


@router.get("/collection", response_class=HTMLResponse)
async def collection_page() -> HTMLResponse:
    return HTMLResponse(inject(COLLECTION_PAGE))


COLLECTION_PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<title>Северо-Юг · Коллекция</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{--up:#3fae6a}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg);color:var(--ink);min-height:100vh;padding-bottom:24px}
.wrap{max-width:520px;margin:0 auto;padding:14px}
.head{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.head .b{background:var(--panel);border:1px solid var(--line);border-radius:999px;
  padding:8px 14px;font-size:13px;font-weight:800}
.head .b.bal{color:var(--acc2)}
.tabs{display:flex;gap:7px;margin-bottom:12px}
.tab{flex:1;border:1px solid var(--line);background:var(--panel);color:var(--muted);
  border-radius:12px;padding:11px;font-size:13px;font-weight:800}
.tab.on{background:var(--acc);color:var(--acc-ink);border-color:transparent}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}
.card{background:var(--panel);border:1.5px solid var(--line);border-radius:13px;padding:7px;
  text-align:center;position:relative;overflow:hidden}
.card img{width:100%;height:58px;object-fit:cover;border-radius:9px;display:block}
.card .ic{font-size:31px;line-height:58px}
.card .nm{font-size:10.5px;font-weight:700;margin-top:5px;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
.card .pr{font-size:9.5px;color:var(--acc2);font-weight:700}
.card .ct{position:absolute;z-index:5;top:4px;right:5px;font-size:10px;
  font-weight:800;color:#fff;background:rgba(8,10,14,.94);
  border:1px solid rgba(255,255,255,.28);border-radius:7px;padding:1px 6px;
  box-shadow:0 2px 7px rgba(0,0,0,.55);line-height:15px}
.r-rare{border-color:rgba(107,114,128,.55)} .r-superrare{border-color:rgba(59,130,246,.7)}
.r-epic{border-color:rgba(168,85,247,.75)} .r-mythic{border-color:rgba(239,68,68,.75)}
.r-legendary{border-color:rgba(234,179,8,.8)} .r-secret{border-color:rgba(100,116,139,.85)}
.r-ultra{border-color:rgba(232,121,249,.9)} .r-teacher{border-color:rgba(194,65,12,.9)}
.empty{text-align:center;color:var(--muted);padding:44px 16px;font-size:13px;line-height:1.6}

/* Свой префикс: классы .sheet/.modal в общем слое конфликтуют. */
.colmask{position:fixed;inset:0;background:rgba(6,8,12,.82);display:none;
  align-items:flex-end;justify-content:center;z-index:9000}
.colmask.on{display:flex}
.colsheet{position:relative;width:100%;max-width:520px;background:var(--panel);
  border:1px solid var(--line);border-radius:20px 20px 0 0;padding:18px 18px 26px;
  max-height:86vh;overflow-y:auto;overscroll-behavior:contain;
  z-index:1;animation:__colup .28s cubic-bezier(.2,.9,.3,1.05)}
@keyframes __colup{from{transform:translateY(30px)}to{transform:none}}
.colx{position:sticky;top:-18px;margin:-18px -18px 10px;padding:12px 16px;
  display:flex;justify-content:flex-end;background:var(--panel);z-index:2;
  border-bottom:1px solid var(--line)}
.colx button{border:1px solid var(--line);background:var(--panel2);color:var(--ink);
  border-radius:10px;width:34px;height:34px;font-size:17px;font-weight:900;line-height:1}
.cvback{margin:0 0 12px;border:1px solid var(--line);background:var(--panel);
  color:var(--ink);border-radius:12px;padding:10px 16px;font-size:13px;font-weight:800}
.cvcard{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px}
.colsheet .top{display:flex;gap:13px;align-items:center}
.colsheet .art{width:76px;height:76px;border-radius:14px;object-fit:cover;flex:0 0 auto;
  background:var(--panel2);display:flex;align-items:center;justify-content:center;font-size:38px}
.colsheet .nm{font-size:19px;font-weight:900;line-height:1.15}
.colsheet .rr{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.7px;margin-top:2px}
.colsheet .pr{font-size:16px;font-weight:900;color:var(--acc2);margin-top:5px}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:14px}
.stats div{background:var(--panel2);border:1px solid var(--line);border-radius:11px;padding:9px;text-align:center}
.stats b{display:block;font-size:16px;font-weight:900}
.stats span{font-size:10px;color:var(--muted);letter-spacing:.5px;text-transform:uppercase}
.block{margin-top:14px;background:var(--panel2);border:1px solid var(--line);border-radius:12px;padding:11px 13px}
.block .t{font-size:10.5px;letter-spacing:1.2px;text-transform:uppercase;color:var(--muted);font-weight:800}
.block .v{font-size:13px;margin-top:4px;line-height:1.5}
.upg{width:100%;margin-top:16px;border:0;border-radius:13px;padding:16px;font-size:15px;
  font-weight:900;background:var(--acc);color:var(--acc-ink)}
.upg[disabled]{background:var(--panel2);color:var(--muted)}
.close{width:100%;margin-top:8px;border:1px solid var(--line);border-radius:13px;padding:13px;
  font-size:13px;font-weight:800;background:transparent;color:var(--muted)}

.flash{position:fixed;inset:0;pointer-events:none;z-index:60;opacity:0;
  background:radial-gradient(circle at 50% 45%,rgba(255,255,255,.95),transparent 62%)}
.flash.on{animation:__flash .9s ease-out}
@keyframes __flash{0%{opacity:0;transform:scale(.2)}30%{opacity:1;transform:scale(1)}
  100%{opacity:0;transform:scale(1.6)}}
.parts{margin-top:14px}
.part{display:flex;align-items:center;gap:10px;background:var(--panel2);
  border:1px solid var(--line);border-radius:12px;padding:11px 13px;margin-bottom:7px;
  opacity:0;transform:translateY(12px) scale(.96);
  animation:__part .45s cubic-bezier(.2,.9,.3,1.06) forwards}
@keyframes __part{to{opacity:1;transform:none}}
.part .i{font-size:24px}
.part .n{font-size:13.5px;font-weight:800}
.part .s{font-size:11.5px;color:var(--muted);margin-top:2px}
#toast{position:fixed;left:14px;right:14px;bottom:16px;background:var(--panel2);color:var(--ink);
  border:1px solid var(--line);border-radius:12px;padding:13px 15px;font-size:13px;
  transform:translateY(220%);transition:.25s;z-index:70}
#toast.on{transform:translateY(0)}
</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <div class="b bal" id="bal">…</div>
    <div class="b" id="cnt">…</div>
  </div>
  <div class="tabs">
    <button class="tab on" id="tabCards">7Г</button>
    <button class="tab" id="tabD">7Д</button>
    <button class="tab" id="tabUpg">Улучшенные</button>
  </div>
  <div id="list"></div>
  <div id="cardView" style="display:none"></div>
</div>

<div class="colmask" id="modal">
  <div class="colsheet" id="sheet"></div>
</div>
<div class="flash" id="flash"></div>
<div id="toast"></div>
<script>
const tg = window.Telegram ? window.Telegram.WebApp : null;
const headers = {"X-Telegram-Init-Data": tg ? tg.initData : "", "Content-Type": "application/json"};
const SLOT = {aura: "\u2728", background: "\uD83D\uDDBC", effect: "\uD83C\uDF00"};
let S = {data: null, tab: "cards", busy: false};

function esc(s){ return String(s == null ? "" : s).replace(/[<>&"]/g, c => ({"<":"&lt;",">":"&gt;","&":"&amp;",'"':"&quot;"}[c])); }
function money(n){ return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, " "); }
function toast(t){
  const el = document.getElementById("toast");
  el.textContent = t; el.className = "on";
  clearTimeout(el._t); el._t = setTimeout(() => el.className = "", 3000);
}
function render(){
  const d = S.data;
  document.getElementById("bal").textContent = "$ " + money(d.balance);
  var cntD = d.cards.filter(function(c){ return String(c.id).indexOf("d_") === 0; }).length;
  document.getElementById("cnt").textContent =
    "7Г: " + (d.total - cntD) + " · 7Д: " + cntD;
  document.getElementById("tabCards").className = "tab" + (S.tab === "cards" ? " on" : "");
  document.getElementById("tabD").className = "tab" + (S.tab === "d" ? " on" : "");
  document.getElementById("tabUpg").className = "tab" + (S.tab === "upg" ? " on" : "");
  if (S.tab === "cards" || S.tab === "d"){
    var isD = function(c){ return String(c.id).indexOf("d_") === 0; };
    var src = S.tab === "d" ? d.cards.filter(isD) : d.cards.filter(function(c){ return !isD(c); });
    document.getElementById("list").innerHTML = src.length
      ? '<div class="grid">' + src.map(c =>
          '<div class="card r-' + c.rarity + '" data-c="' + c.id + '">' +
          (c.count > 1 ? '<div class="ct">\u00d7' + c.count + '</div>' : '') +
          (c.image ? '<img src="' + esc(c.image) + '" alt="">' : '<div class="ic">' + c.emoji + '</div>') +
          '<div class="nm">' + esc(c.name) + '</div>' +
          '<div class="pr">' + money(c.price) + '</div></div>').join("") + '</div>'
      : '<div class="empty">' + (S.tab === "d"
          ? "Коллекция 7Д пуста.<br>Напиши «западо-восток» или открой кейс «7Д класс»."
          : "Пусто. Выбей карту командой «Северо-Юг».") + '</div>';
    document.querySelectorAll("[data-c]").forEach(el => el.onclick = () => openCard(el.dataset.c));
  } else {
    document.getElementById("list").innerHTML = d.upgraded.length
      ? '<div class="grid">' + d.upgraded.map(u =>
          '<div class="card">' +
          (u.image ? '<img src="' + esc(u.image) + '" alt="">' : '<div class="ic">' + u.emoji + '</div>') +
          '<div class="nm">' + esc(u.name) + '</div>' +
          '<div class="pr">' + money(u.price) + '</div></div>').join("") + '</div>'
      : '<div class="empty">Улучшенных копий пока нет.<br>Открой карту и нажми «Улучшить».</div>';
  }
}
function openCard(id){
  const c = S.data.cards.find(x => x.id === id);
  if (!c) return;
  const can = S.data.balance >= S.data.upgrade_price && c.count > 0;
  var view = document.getElementById("cardView");
  view.innerHTML =
    '<button class="cvback" id="cvBack">\u2190 Назад</button>' +
    '<div class="cvcard">' +
    '<div class="top">' +
      (c.image ? '<img class="art" src="' + esc(c.image) + '" alt="">'
               : '<div class="art">' + c.emoji + '</div>') +
      '<div><div class="nm">' + esc(c.name) + '</div>' +
      '<div class="rr">' + esc(c.rarity_title) + '</div>' +
      '<div class="pr">' + money(c.price) + ' очк.</div></div></div>' +
    '<div class="stats">' +
      '<div><b>' + c.hp + '</b><span>HP</span></div>' +
      '<div><b>' + c.atk + '</b><span>атака</span></div>' +
      '<div><b>\u00d7' + c.count + '</b><span>копий</span></div></div>' +
    '<div class="block"><div class="t">Способность</div><div class="v"><b>' +
      esc(c.ability) + '</b><br>' + esc(c.ability_text) + '</div></div>' +
    (c.description ? '<div class="block"><div class="t">Описание</div><div class="v">' +
      esc(c.description) + '</div></div>' : '') +
    '<div id="upgResult"></div>' +
    '<button class="upg" id="upgBtn"' + (can ? "" : " disabled") + '>Улучшить за ' +
      money(S.data.upgrade_price) + ' очк.</button>' +
    '</div>';
  document.getElementById("list").style.display = "none";
  var tabs = document.querySelector(".tabs");
  if (tabs) tabs.style.display = "none";
  view.style.display = "block";
  window.scrollTo(0, 0);
  const b = document.getElementById("upgBtn");
  if (b) b.onclick = () => upgrade(c.id);
  const back = document.getElementById("cvBack");
  if (back) back.onclick = closeModal;
}
function closeModal(){
  var v = document.getElementById("cardView");
  if (v) v.style.display = "none";
  document.getElementById("list").style.display = "";
  var tabs = document.querySelector(".tabs");
  if (tabs) tabs.style.display = "";
}
async function upgrade(cardId){
  if (S.busy) return;
  S.busy = true;
  const btn = document.getElementById("upgBtn");
  if (btn){ btn.disabled = true; btn.textContent = "Улучшаем…"; }
  try{
    const r = await fetch("/api/collection/upgrade", {method:"POST", headers,
      body: JSON.stringify({card_id: cardId})});
    const d = await r.json();
    if (d.error){ toast(d.error); }
    else {
      const flash = document.getElementById("flash");
      flash.classList.remove("on");
      void flash.offsetWidth;
      flash.classList.add("on");
      if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
      const box = document.getElementById("upgResult");
      if (box){
        box.innerHTML = '<div class="parts">' + d.items.map((it, i) =>
          '<div class="part" style="animation-delay:' + (0.25 + i * 0.18) + 's">' +
          '<div class="i">' + (SLOT[it.slot] || "\u2728") + '</div>' +
          '<div><div class="n">' + esc(it.name) + '</div>' +
          '<div class="s">' + esc(it.summary) + '</div></div></div>').join("") + '</div>';
      }
      if (btn){ btn.textContent = "Готово"; btn.disabled = true; }
      await load();
    }
  }catch(e){ toast("Связь потерялась"); }
  S.busy = false;
}
async function load(){
  try{
    const r = await fetch("/api/collection", {headers});
    const d = await r.json();
    if (d.error){ toast(d.error); return; }
    S.data = d; render();
  }catch(e){ toast("Не смог загрузить"); }
}
document.getElementById("tabCards").onclick = () => { S.tab = "cards"; render(); };
document.getElementById("tabD").onclick = () => { S.tab = "d"; render(); };
document.getElementById("tabUpg").onclick = () => { S.tab = "upg"; render(); };
if(tg){ tg.ready(); tg.expand(); }
load();
</script>
</body>
</html>
"""


@router.post("/api/case/open_many")
async def api_case_open_many(request: Request) -> JSONResponse:
    """Открыть сразу несколько кейсов — для мульти-ленты."""
    state = request.app.state
    uid, error = await _games_user(request)
    if error is not None:
        return error
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    try:
        want = int((body or {}).get("count", 1))
    except (TypeError, ValueError):
        want = 1
    want = max(1, min(10, want))

    cases = await state.db.user_cases(uid)
    if not cases:
        return JSONResponse({"error": "Кейсов нет — крути рулетку"}, status_code=400)
    want_d = str((body or {}).get("kind", "g")) == "d"
    picked = [
        c
        for c in cases
        if (str(c.get("source") or "") == cases_mod.CASE_D_SOURCE) == want_d
    ]
    if not picked:
        return JSONResponse(
            {"error": "Кейсов 7Д нет" if want_d else "Кейсов 7Г нет"},
            status_code=400,
        )

    opened: list[dict[str, Any]] = []
    for case in picked[:want]:
        if not await state.db.open_case(uid, int(case["id"])):
            continue
        # Пул строго по типу кейса: 7Д не может выдать карту 7Г.
        case_is_d = str(case.get("source") or "") == cases_mod.CASE_D_SOURCE
        card = cases_mod.roll_case_d() if case_is_d else roll_case_card()
        counts = await state.db.get_collection(uid)
        is_new = card.card_id not in counts
        await state.db.add_card(uid, card.card_id)
        await state.db.add_points(uid, card.points)
        opened.append(
            {
                "id": card.card_id,
                "name": card.name,
                "emoji": card.rarity_emoji,
                "rarity": card.rarity,
                "rarity_title": rarity_name(card.rarity),
                "points": card.points,
                "price": market_price(card),
                "color": cases_mod.RARITY_COLORS.get(card.rarity, "#334155"),
                "is_new": is_new,
            }
        )
    if not opened:
        return JSONResponse({"error": "Не получилось открыть"}, status_code=400)
    all_cases = await state.db.user_cases(uid)
    return JSONResponse(
        {
            "ok": True,
            "cards": opened,
            "cases": len(all_cases),
            "count_g": sum(
                1 for c in all_cases
                if str(c.get("source") or "") != cases_mod.CASE_D_SOURCE
            ),
            "count_d": sum(
                1 for c in all_cases
                if str(c.get("source") or "") == cases_mod.CASE_D_SOURCE
            ),
        }
    )


@router.post("/api/case/buy_d")
async def api_case_buy_d(request: Request) -> JSONResponse:
    """Купить кейс «7Д класс»: 350 000, с VIP — 250 000."""
    state = request.app.state
    uid, error = await _games_user(request)
    if error is not None:
        return error
    vip = await state.db.vip_active(uid)
    price = cases_mod.CASE_D_PRICE_VIP if vip else cases_mod.CASE_D_PRICE
    ok = await state.db.buy_case_d(uid, price)
    if not ok:
        return JSONResponse(
            {"error": f"Не хватает очков: нужно {price}"}, status_code=400
        )
    return JSONResponse(
        {
            "ok": True,
            "price": price,
            "vip": vip,
            "cases": len(await state.db.user_cases(uid)),
        }
    )


# --------------------------------------------------------------------------- #
# Задания — ежедневные квесты + PvP-стрик
# --------------------------------------------------------------------------- #


@router.get("/api/quests")
async def api_quests(request: Request) -> JSONResponse:
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    uid = int(user["id"])
    repo = getattr(state, "quests", None)
    if repo is None:
        return JSONResponse({"error": "Квесты ещё не включены"}, status_code=400)
    items = await repo.list(uid)
    async with state.db.pool.acquire() as con:  # type: ignore[attr-defined]
        streak = int(
            await con.fetchval(
                "select coalesce(pvp_streak, 0) from players where user_id = $1", uid
            )
            or 0
        )
        wins = int(
            await con.fetchval(
                "select coalesce(wins, 0) from players where user_id = $1", uid
            )
            or 0
        )
    return JSONResponse(
        {
            "quests": items,
            "done": sum(1 for q in items if q["done"]),
            "claimed": sum(1 for q in items if q["claimed"]),
            "ready": sum(1 for q in items if q["done"] and not q["claimed"]),
            "total": len(items),
            "pvp": {
                "streak": streak,
                "wins": wins,
                "steps": [
                    {"need": 3, "cases": 5, "reached": streak >= 3},
                    {"need": 10, "cases": 15, "reached": streak >= 10},
                ],
            },
        }
    )


@router.post("/api/quests/claim")
async def api_quests_claim(request: Request) -> JSONResponse:
    """Забрать награду за выполненный квест. Ровно один раз на квест."""
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)
    repo = getattr(state, "quests", None)
    if repo is None:
        return JSONResponse({"error": "Квесты ещё не включены"}, status_code=400)
    body = await _json_body(request)
    try:
        result = await repo.claim(int(user["id"]), body.get("key"))
    except QuestError as error:
        return JSONResponse({"ok": False, "error": str(error)}, status_code=400)
    return JSONResponse({"ok": True, **result})


@router.get("/quests", response_class=HTMLResponse)
async def quests_page() -> HTMLResponse:
    return HTMLResponse(inject(QUESTS_PAGE))


QUESTS_PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<title>Северо-Юг · Задания</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg);color:var(--ink);min-height:100vh;padding-bottom:24px}
.wrap{max-width:520px;margin:0 auto;padding:14px}
.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.top .b{background:var(--panel);border:1px solid var(--line);border-radius:999px;
  padding:8px 14px;font-size:13px;font-weight:800}
.top .b.ok{color:#26a69a}
.q{background:var(--panel);border:1px solid var(--line);border-radius:14px;
  padding:13px 15px;margin-bottom:8px}
.q.done{border-color:#26a69a}
.q .h{display:flex;justify-content:space-between;gap:10px;align-items:baseline}
.q .t{font-size:13.5px;font-weight:700}
.q .n{font-size:12px;color:var(--muted);font-weight:700;
  font-family:'JetBrains Mono',ui-monospace,monospace}
.q.done .n{color:#26a69a}
.bar{height:7px;background:var(--panel2);border-radius:99px;overflow:hidden;margin-top:8px}
.bar i{display:block;height:100%;background:var(--acc);border-radius:99px}
.q.done .bar i{background:#26a69a}
.q .rw{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-top:9px}
.q .rw span{font-size:11.5px;color:var(--muted)}
.claim{border:0;border-radius:9px;padding:7px 13px;font-family:inherit;font-size:11px;
  font-weight:800;background:var(--acc);color:#08131a}
.claim:disabled{opacity:.5}
.claim.got{background:none;color:#26a69a;padding:7px 0}
.claim.wait{background:none;color:var(--muted);padding:7px 0;font-size:10.5px}
.note{font-size:11.5px;color:var(--muted);margin:2px 0 10px}
.pvp{background:var(--panel);border:1px solid var(--line);border-radius:14px;
  padding:15px;margin-top:14px}
.pvp h3{margin:0 0 4px;font-size:15px}
.pvp .st{font-size:32px;font-weight:900;color:#f6c94a;line-height:1.1;
  font-family:'JetBrains Mono',ui-monospace,monospace}
.pvp .sub{font-size:12px;color:var(--muted);margin-top:4px}
.step{display:flex;justify-content:space-between;align-items:center;
  background:var(--panel2);border:1px solid var(--line);border-radius:11px;
  padding:11px 13px;margin-top:8px;font-size:13px}
.step.on{border-color:#26a69a;color:#26a69a}
.step b{font-family:'JetBrains Mono',ui-monospace,monospace}
#toast{position:fixed;left:14px;right:14px;bottom:16px;background:var(--panel2);
  color:var(--ink);border:1px solid var(--line);border-radius:12px;padding:13px 15px;
  font-size:13px;transform:translateY(220%);transition:.25s;z-index:30}
#toast.on{transform:translateY(0)}
.apps{display:flex;gap:6px;margin:0 0 12px;background:var(--panel);
  border:1px solid var(--line);border-radius:999px;padding:4px}
.apps a{flex:1;text-align:center;text-decoration:none;color:var(--muted);
  font-weight:800;font-size:12px;padding:9px 4px;border-radius:999px;white-space:nowrap}
.apps a.on{background:var(--acc);color:var(--acc-ink)}
</style>
</head>
<body>
<div class="wrap">
  <nav class="apps">
    <a href="/yugi">🍁 Кликер</a>
    <a href="/proto_dungeon">🗡 Подземелье</a>
    <a class="on" href="/quests">📜 Задания</a>
  </nav>

  <div class="top">
    <div class="b" id="cnt">…</div>
    <div class="b ok" id="streak">…</div>
  </div>
  <div id="list"></div>
  <div class="note">Награда за задание забирается кнопкой — один раз за каждое.</div>
  <div class="pvp" id="pvp"></div>
</div>
<div id="toast"></div>
<script>
const tg = window.Telegram ? window.Telegram.WebApp : null;
const headers = {"X-Telegram-Init-Data": tg ? tg.initData : "", "Content-Type": "application/json"};
function esc(s){ return String(s == null ? "" : s).replace(/[<>&"]/g, c => ({"<":"&lt;",">":"&gt;","&":"&amp;",'"':"&quot;"}[c])); }
function toast(t){
  const el = document.getElementById("toast");
  el.textContent = t; el.className = "on";
  clearTimeout(el._t); el._t = setTimeout(() => el.className = "", 2800);
}
async function load(){
  try{
    const r = await fetch("/api/quests", {headers});
    const d = await r.json();
    if (d.error){ toast(d.error); return; }
    document.getElementById("cnt").textContent = "Выполнено " + d.done + " из " + d.total +
      (d.claimed ? " · забрано " + d.claimed : "");
    document.getElementById("streak").textContent = "🔥 стрик " + d.pvp.streak;
    document.getElementById("list").innerHTML = d.quests.map(q => {
      const pct = Math.min(100, Math.round(q.now / q.need * 100));
      let action;
      if (q.claimed) action = '<span class="claim got">ПОЛУЧЕНО</span>';
      else if (q.done) action = '<button class="claim" data-claim="' + esc(q.key) + '">ЗАБРАТЬ</button>';
      else action = '<span class="claim wait">' + q.now + " из " + q.need + '</span>';
      return '<div class="q' + (q.done ? " done" : "") + (q.claimed ? " got" : "") + '">' +
        '<div class="h"><div class="t">' + esc(q.title) + '</div>' +
        '<div class="n">' + q.now + "/" + q.need + '</div></div>' +
        '<div class="bar"><i style="width:' + pct + '%"></i></div>' +
        '<div class="rw"><span>' + esc(q.reward_text) + '</span>' + action + '</div></div>';
    }).join("");
    const p = d.pvp;
    document.getElementById("pvp").innerHTML =
      '<h3>⚔️ PvP-стрик</h3>' +
      '<div class="st">' + p.streak + '</div>' +
      '<div class="sub">побед подряд · всего побед ' + p.wins + '</div>' +
      p.steps.map(s =>
        '<div class="step' + (s.reached ? " on" : "") + '">' +
        '<span>' + s.need + ' побед подряд</span>' +
        '<b>' + (s.reached ? "✓ " : "") + '+' + s.cases + ' кейсов</b></div>').join("") +
      '<div class="sub" style="margin-top:10px">Кейсы за стрик приходят автоматически. ' +
      'Больше 5 боёв с одним и тем же игроком — стрик сгорает, \n       минус 250 000 очков, все кейсы и бан PvP на неделю.</div>';
  }catch(e){ toast("Не смог загрузить"); }
}
document.getElementById("list").addEventListener("click", async function(e){
  const btn = e.target && e.target.closest ? e.target.closest("[data-claim]") : null;
  if (!btn) return;
  btn.disabled = true;
  try{
    const r = await fetch("/api/quests/claim", {
      method: "POST", headers,
      body: JSON.stringify({key: btn.dataset.claim})
    });
    const d = await r.json();
    if (!d.ok){ toast(d.error || "Не вышло"); btn.disabled = false; return; }
    toast("Награда: " + d.reward_text);
    load();
  }catch(err){ toast("Не смог забрать"); btn.disabled = false; }
});
if (tg){ tg.ready(); tg.expand(); }
load();
</script>
</body>
</html>
"""


PROTO_PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<title>Прототип · Юга-кликер</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0}
body{font-family:"Trebuchet MS",-apple-system,"Segoe UI",Roboto,sans-serif;
  background:#3b2417;color:#f3e6c8;min-height:100vh;padding-bottom:20px}
.wrap{max-width:760px;margin:0 auto;padding:10px}
.panel{background:linear-gradient(#4a2e1c,#3a2314);border:3px solid #7a5330;border-radius:12px}
.left{display:flex;flex-direction:column;align-items:center;gap:8px;padding:12px}
.count{font-size:22px;font-weight:900;color:#ffd98a;text-shadow:0 2px 0 #2a170c;text-align:center}
.count small{display:block;font-size:12px;color:#c9a878;font-weight:700}
.cookie{width:190px;height:190px;border-radius:50%;border:0;cursor:pointer;
  background:radial-gradient(circle at 35% 30%,#e8b96a,#a9691f 65%,#6b3d0d);
  box-shadow:0 0 0 8px #d8c39a,0 0 0 12px #6b4a22,0 14px 30px rgba(0,0,0,.55);
  font-size:74px;display:flex;align-items:center;justify-content:center;
  transition:transform .05s}
.cookie:active{transform:scale(.955)}
.cps{font-size:13px;color:#e7c98d;font-weight:800;font-family:ui-monospace,monospace}
.buffs{display:flex;flex-wrap:wrap;gap:5px;justify-content:center;min-height:18px}
.buff{font-size:10.5px;font-weight:800;border-radius:99px;padding:4px 10px;
  background:#6b3d0d;color:#ffd98a;border:1px solid #b98a3d}
.street{margin:6px 0;padding:6px 8px;border-radius:10px;border:2px solid #6b4a22;
  background:linear-gradient(#5c3a20,#43280f);position:relative;overflow:hidden}
.street .lbl{font-size:10px;letter-spacing:1px;text-transform:uppercase;color:#c9a878;font-weight:800;margin-bottom:3px}
.street .row2{display:flex;flex-wrap:wrap;gap:1px;font-size:22px;line-height:1;max-height:52px;overflow:hidden}
.street .num{position:absolute;right:9px;top:7px;font-size:13px;font-weight:900;
  color:#ffd98a;font-family:ui-monospace,monospace;text-shadow:0 1px 3px #000}

#particles{position:fixed;inset:0;pointer-events:none;z-index:1;overflow:hidden}
#particles i{position:absolute;top:-50px;opacity:.3;animation:fall linear infinite;
  will-change:transform}
@keyframes fall{to{transform:translateY(118vh) rotate(420deg)}}
.pop{position:fixed;pointer-events:none;font-weight:900;color:#ffd98a;font-size:19px;
  z-index:55;animation:popup .95s cubic-bezier(.2,.8,.3,1) forwards;
  text-shadow:0 2px 8px #000;font-family:ui-monospace,monospace}
@keyframes popup{0%{transform:translate(-50%,-50%) scale(.7);opacity:1}
  100%{transform:translate(-50%,-190%) scale(1.15);opacity:0}}
.cookie.squash{animation:squash .13s ease}
@keyframes squash{50%{transform:scale(.9)}}
.street{animation:streetIn .35s cubic-bezier(.2,.9,.3,1.05)}
@keyframes streetIn{from{transform:scale(.92);opacity:0}to{transform:none;opacity:1}}
.item.flash{animation:flash .45s ease}
@keyframes flash{0%{background:#8a5a28}100%{background:transparent}}
.burst{position:fixed;pointer-events:none;z-index:54;font-size:20px;
  animation:burst .7s ease-out forwards}
@keyframes burst{to{transform:translate(var(--dx),var(--dy)) scale(.3);opacity:0}}
#treemodal{position:fixed;inset:0;background:rgba(18,9,4,.95);z-index:70;
  display:none;flex-direction:column}
#treemodal.on{display:flex}
.tmhead{display:flex;justify-content:space-between;align-items:center;
  padding:12px 16px;border-bottom:2px solid #6b4a22;color:#ffd98a;
  font-weight:900;font-size:15px}
.tmhead button{border:2px solid #6b4a22;background:#4a2e1c;color:#ffd98a;
  border-radius:8px;padding:7px 14px;font-size:13px;font-weight:800;font-family:inherit}
.tmbody{flex:1;overflow:hidden;position:relative;cursor:grab;touch-action:none}
.tmbody:active{cursor:grabbing}
.tmbody svg{position:absolute;left:0;top:0;will-change:transform}
.tmhint{position:absolute;left:0;right:0;bottom:10px;text-align:center;
  font-size:11px;color:#a98a5f;pointer-events:none}
.treewrap{background:#241408;border-radius:0 0 10px 10px}
.treewrap svg{display:block}
.node{cursor:pointer}
.node circle{transition:stroke .15s,fill .15s}
.node text.lbl{font-size:10px;fill:#ffd98a;font-weight:800;
  font-family:ui-monospace,monospace}
.node.on circle{fill:#8a5a28;stroke:#ffd98a}
.node.can circle{fill:#4a2e1c;stroke:#8bd65a}
.node.lock circle{fill:#2a1a0e;stroke:#5a3a1e}
.node.lock{opacity:.55}
.tabs{display:flex;gap:4px;padding:6px}
.tabs button{flex:1;border:2px solid #6b4a22;background:#4a2e1c;border-radius:8px;
  padding:8px 0;font-size:16px;font-family:inherit;cursor:pointer}
.tabs button.on{background:#8a5a28;border-color:#d8b45a}
.item{display:flex;align-items:center;gap:8px;padding:8px 9px;border-top:1px solid #5a3a1e;
  cursor:pointer;user-select:none}
.item:active{background:#5c3a20}
.item.off{opacity:.42}
.item .ic{font-size:20px;width:26px;text-align:center}
.item .tx{flex:1;min-width:0}
.item .nm{font-size:12.5px;font-weight:800;color:#ffe9b8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.item .pr{font-size:11px;color:#c9a878;font-family:ui-monospace,monospace}
.item .ct{font-size:15px;font-weight:900;color:#8bd65a;font-family:ui-monospace,monospace}
.item.up .nm{color:#9fd6ff}
.ctl{display:flex;gap:6px;padding:8px}
.ctl button{flex:1;border:2px solid #6b4a22;background:#4a2e1c;color:#c9a878;
  border-radius:8px;padding:10px;font-size:11.5px;font-weight:800;font-family:inherit;cursor:pointer}
#gold{position:fixed;font-size:44px;cursor:pointer;z-index:50;display:none;
  filter:drop-shadow(0 0 16px rgba(255,215,100,.95));animation:pulse 1s ease-in-out infinite}
@keyframes pulse{0%,100%{transform:scale(1) rotate(-8deg)}50%{transform:scale(1.18) rotate(8deg)}}
#toast{position:fixed;left:12px;right:12px;bottom:14px;background:#6b3d0d;color:#ffe9b8;
  border:2px solid #b98a3d;border-radius:10px;padding:12px 14px;font-size:13px;font-weight:700;
  transform:translateY(240%);transition:.25s;z-index:60}
#toast.on{transform:translateY(0)}
@media(min-width:640px){
  .wrap{display:grid;grid-template-columns:230px 1fr 210px;gap:10px;align-items:start}
  .left{grid-column:1}.center{grid-column:2}.shop{grid-column:3}
}
</style>
</head>
<body>
<div class="wrap">
  <div class="left panel">
    <div class="count"><span id="bal">0</span><small id="cpsl">в секунду: 0</small></div>
    <button class="cookie" id="tap">🍪</button>
    <div class="cps" id="tapv">+1 за клик</div>
    <div class="buffs" id="buffs"></div>
    <div class="cps" id="chipline" style="font-size:11px;color:#c9a878">фишек: 0</div>
  </div>
  <div class="center" id="streets"><div class="panel" style="padding:26px;text-align:center;color:#a98a5f;font-size:13px">Купи первое здание справа</div></div>
  <div class="shop panel">
    <div class="tabs" id="tabs">
      <button data-tab="b" class="on">🏠</button><button data-tab="u">⬆️</button><button data-tab="a">🏆</button>
    </div>
    <div id="shop"></div>
    <div class="ctl"><button id="ascend">Вознестись</button><button id="reset">Сброс</button></div>
    <div id="ascinfo" style="padding:0 9px 9px;font-size:10px;color:#a98a5f;text-align:center"></div>
  </div>
</div>
<div id="treemodal"><div class="tmhead"><span>🌳 Древо престижа</span>
<button id="tmclose">Закрыть</button></div>
<div class="tmbody" id="tmb"><div class="tmhint">тяни пальцем или мышкой</div></div></div>
<div id="particles"></div>
<div id="gold">🍪</div>
<div id="toast"></div>
<script>
const BUILDINGS = [
  {id:"cur", n:"Курсор", e:"👆", base:15, cps:0.1},
  {id:"yuga", n:"Юга-мастер", e:"🧑", base:100, cps:0.8},
  {id:"farm", n:"Ферма", e:"🌱", base:1100, cps:5},
  {id:"mine", n:"Шахта", e:"⛏", base:12000, cps:30},
  {id:"factory", n:"Фабрика", e:"🏭", base:130000, cps:180},
  {id:"bank", n:"Банк", e:"🏦", base:1400000, cps:1100},
  {id:"portal", n:"Портал", e:"🌀", base:20000000, cps:7500},
  {id:"prism", n:"Призма", e:"💎", base:330000000, cps:50000},
  {id:"ship", n:"Корабль", e:"🚀", base:5.1e9, cps:350000},
  {id:"lab", n:"Лаборатория", e:"⚗️", base:7.5e10, cps:2500000},
  {id:"time", n:"Машина времени", e:"⏳", base:1e12, cps:18000000},
  {id:"anti", n:"Антиматерия", e:"🌀", base:1.4e13, cps:130000000},
  {id:"chance", n:"Делатель удачи", e:"🍀", base:1.7e14, cps:9e8},
  {id:"engine", n:"Фрактал", e:"🧩", base:2.1e15, cps:6e9},
  {id:"idle", n:"Идлверс", e:"🌌", base:2.6e16, cps:4.5e10},
];
const TREE = [];
(function(){
  var pcts = [10, 25, 50, 100, 200, 500];
  var price = [1, 2, 4, 8, 16, 32];
  BUILDINGS.forEach(function(b){
    pcts.forEach(function(p, i){
      TREE.push({
        id: "t_" + b.id + "_" + i,
        n: b.n,
        e: b.e,
        pct: p,
        bid: b.id,
        cost: price[i],
        grp: b.n
      });
    });
  });
  var glob = [
    ["Клик +50%", "👆", 2], ["Клик +100%", "👆", 5], ["Клик ×2", "👆", 14],
    ["Золотые чаще", "🍪", 3], ["Золотые чаще II", "🍪", 9],
    ["Старт: 10 курсоров", "🎁", 6], ["Старт: 25 курсоров", "🎁", 20],
    ["+10% ко всему", "🌟", 4], ["+25% ко всему", "🌟", 12],
    ["+50% ко всему", "🌟", 30], ["+100% ко всему", "🌟", 70],
    ["Фишек +10%", "💠", 15], ["Фишек +25%", "💠", 45],
    ["Производство ×1.5", "⚡", 25], ["Производство ×2", "⚡", 90],
    ["Достижения +x2", "🏆", 18], ["Вознесение дешевле", "🌀", 22],
    ["Молоко +50%", "🥛", 8], ["Улицы ярче", "✨", 1], ["Частицы гуще", "✨", 1]
  ];
  glob.forEach(function(g, i){
    TREE.push({ id: "g_" + i, n: g[0], e: g[1], cost: g[2], pct: 0, grp: "Общее" });
  });
})();
function treeHas(id){ return S.tree.indexOf(id) >= 0; }
var pan = {x:0, y:0, drag:false, sx:0, sy:0, ox:0, oy:0, moved:0};
function applyPan(){
  var svg = document.querySelector("#tmb svg");
  if (svg) svg.style.transform = "translate(" + pan.x + "px," + pan.y + "px)";
}
function openTree(){
  var m = document.getElementById("treemodal");
  m.classList.add("on");
  pan.x = 0; pan.y = 0;
  document.getElementById("tmb").innerHTML = treeSVG() +
    '<div class="tmhint">тяни пальцем или мышкой</div>';
  applyPan();
}
function closeTree(){ document.getElementById("treemodal").classList.remove("on"); }
function treeSVG(){
  var groups = {}, order = [];
  TREE.forEach(function(t){
    if (t.grp === "Общее") return;
    if (!groups[t.grp]){ groups[t.grp] = []; order.push(t.grp); }
    groups[t.grp].push(t);
  });
  var pos = {}, lines = "", nodes = "";
  order.forEach(function(g, gi){
    var col = gi % 4, block = Math.floor(gi / 4);
    var bx = col * 330 + 110, by = block * 620 + 70;
    groups[g].forEach(function(t, li){
      var x = bx, y = by + li * 90;
      pos[t.id] = {x: x, y: y};
      if (li > 0){
        var pv = pos[groups[g][li - 1].id];
        lines += '<line x1="' + pv.x + '" y1="' + (pv.y + 27) + '" x2="' + x +
          '" y2="' + (y - 27) + '" stroke="#6b4a22" stroke-width="2" stroke-dasharray="5 4"/>';
      }
    });
  });
  var globals = TREE.filter(function(t){ return t.grp === "Общее"; });
  var gy0 = Math.ceil(order.length / 4) * 620 + 30;
  globals.forEach(function(t, i){
    var x = (i % 5) * 300 + 110, y = gy0 + Math.floor(i / 5) * 120;
    pos[t.id] = {x: x, y: y};
    if (i % 5 > 0){
      var pv = pos[globals[i - 1].id];
      lines += '<line x1="' + (pv.x + 27) + '" y1="' + pv.y + '" x2="' + (x - 27) +
        '" y2="' + y + '" stroke="#6b4a22" stroke-width="2" stroke-dasharray="5 4"/>';
    }
  });
  TREE.forEach(function(t){
    var pp = pos[t.id];
    if (!pp) return;
    var on = treeHas(t.id), can = S.chips >= t.cost;
    var cls = on ? "on" : (can ? "can" : "lock");
    nodes += '<g class="node ' + cls + '" data-tree="' + t.id + '" transform="translate(' +
      pp.x + ',' + pp.y + ')">' +
      '<circle r="28" stroke-width="3"/>' +
      '<text y="7" text-anchor="middle" font-size="20">' + t.e + '</text>' +
      (t.pct ? '<text class="lbl" y="48" text-anchor="middle">+' + t.pct + '%</text>' : '') +
      '<text class="lbl" y="' + (t.pct ? 62 : 48) + '" text-anchor="middle">' +
      (on ? "✓" : t.cost) + '</text></g>';
  });
  var W = 4 * 330 + 140, H = gy0 + Math.ceil(globals.length / 5) * 120 + 70;
  return '<div class="treewrap"><svg width="' + W + '" height="' + H + '">' +
    lines + nodes + '</svg></div>';
}
function treeBoost(bid){
  var pcts = [10, 25, 50, 100, 200, 500], m = 1;
  for (var i = 0; i < pcts.length; i++){
    if (treeHas("t_" + bid + "_" + i)) m *= (1 + pcts[i] / 100);
  }
  return m;
}
function treeGlobal(){
  var m = 1, i;
  for (i = 0; i < TREE.length; i++){
    var t = TREE[i];
    if (!treeHas(t.id) || t.bid) continue;
    if (t.n.indexOf("+10% ко всему") === 0) m *= 1.10;
    else if (t.n.indexOf("+25% ко всему") === 0) m *= 1.25;
    else if (t.n.indexOf("+50% ко всему") === 0) m *= 1.50;
    else if (t.n.indexOf("+100% ко всему") === 0) m *= 2.0;
    else if (t.n.indexOf("Производство ×1.5") === 0) m *= 1.5;
    else if (t.n.indexOf("Производство ×2") === 0) m *= 2.0;
  }
  return m;
}
const UPGRADES = [];
(function(){
  // 6 уровней на каждое из 15 зданий = 90
  var th = [5, 10, 25, 50, 100, 150];
  var cm = [20, 200, 2000, 20000, 200000, 2000000];
  BUILDINGS.forEach(function(b){
    th.forEach(function(need, i){
      UPGRADES.push({
        id: b.id + "_" + i,
        n: b.n + " ×2",
        d: "нужно " + need + " шт",
        cost: Math.ceil(b.base * cm[i]),
        bid: b.id,
        check: (function(bb, nn){ return function(){ return own(bb.id) >= nn; }; })(b, need)
      });
    });
  });
  // 10 глобальных «+N% ко всему» = 100
  for (var p = 5; p <= 50; p += 5){
    (function(pp){
      UPGRADES.push({
        id: "g" + pp,
        n: "Общий рост +" + pp + "%",
        d: "+" + pp + "% ко всему",
        cost: Math.ceil(50000 * Math.pow(30, pp / 5 - 1)),
        check: function(){ return S.total >= 50000 * Math.pow(30, pp / 5 - 1); }
      });
    })(p);
  }
})();
const ACH = [
  {id:"c1", n:"10 кликов", check:()=>S.clicks>=10},
  {id:"c2", n:"100 кликов", check:()=>S.clicks>=100},
  {id:"c3", n:"1000 кликов", check:()=>S.clicks>=1000},
  {id:"b1", n:"первое здание", check:()=>Object.values(S.b).some(v=>v>0)},
  {id:"b2", n:"10 зданий", check:()=>Object.values(S.b).reduce((a,b)=>a+b,0)>=10},
  {id:"b3", n:"50 зданий", check:()=>Object.values(S.b).reduce((a,b)=>a+b,0)>=50},
  {id:"b4", n:"100 зданий", check:()=>Object.values(S.b).reduce((a,b)=>a+b,0)>=100},
  {id:"g1", n:"печенька", check:()=>S.golden>=1},
  {id:"g2", n:"5 печенек", check:()=>S.golden>=5},
  {id:"p1", n:"вознесение", check:()=>S.resets>=1},
  {id:"p2", n:"5 вознесений", check:()=>S.resets>=5},
];
const KEY = "yugi_proto_v3";
let S = {bal:0,total:0,clicks:0,golden:0,chips:0,resets:0,b:{},u:[],tree:[],tab:"b"};
let buffs = [];
let dirty = true;   // нужно перерисовать списки

function own(id){ return S.b[id] || 0; }
function has(id){ return S.u.indexOf(id) >= 0; }
function achCount(){ return ACH.filter(a=>a.check()).length; }
function tapPower(){
  var v = 1;
  if (has("tap2")) v += 1;
  if (has("tap5")) v *= 2;
  if (has("tap10")) v *= 3;
  if (treeHas("g_0")) v *= 1.5;
  if (treeHas("g_1")) v *= 2.0;
  if (treeHas("g_2")) v *= 2.0;
  v *= (1 + S.chips * 0.01);
  if (buffActive("click")) v *= 777;
  return v;
}
function cps(){
  var v = 0;
  BUILDINGS.forEach(function(b){
    var m = treeBoost(b.id);
    for (var i = 0; i < 6; i++){ if (has(b.id + "_" + i)) m *= 2; }
    v += own(b.id) * b.cps * m;
  });
  for (var p = 5; p <= 50; p += 5){ if (has("g" + p)) v *= (1 + p / 100); }
  v *= treeGlobal();
  v *= (1 + S.chips * 0.01);
  v *= (1 + achCount() * 0.01);
  if (buffActive("frenzy")) v *= 7;
  return v;
}
function cost(b, count){
  var c = 0, o = own(b.id);
  for (var i = 0; i < count; i++) c += Math.ceil(b.base * Math.pow(1.15, o + i));
  return c;
}
const SUF = ["","K","M","B","T","Qa","Qi","Sx","Sp","Oc","No","Dc"];
function fmt(n){
  n = Math.floor(n);
  if (n < 1000) return String(n);
  var i = 0;
  while (n >= 1000 && i < SUF.length - 1){ n /= 1000; i++; }
  return (n < 10 ? n.toFixed(2) : n < 100 ? n.toFixed(1) : Math.floor(n)) + SUF[i];
}
function buffActive(k){ return buffs.some(b => b.kind === k && b.until > Date.now()); }
function addBuff(k, ms){ buffs.push({kind:k, until: Date.now() + ms}); }
function toast(t){
  var el = document.getElementById("toast");
  el.textContent = t; el.className = "on";
  clearTimeout(el._t); el._t = setTimeout(function(){ el.className = ""; }, 2600);
}
function makeParticles(){
  var box = document.getElementById("particles");
  var gl = ["🍪","✦","·","🍪","🌾"];
  var html = "";
  for (var i = 0; i < 26; i++){
    var dur = 9 + Math.random() * 14;
    html += '<i style="left:' + (Math.random() * 100) + 'vw;font-size:' +
      (10 + Math.random() * 14) + 'px;animation-duration:' + dur.toFixed(1) +
      's;animation-delay:-' + (Math.random() * dur).toFixed(1) + 's">' +
      gl[Math.floor(Math.random() * gl.length)] + '</i>';
  }
  box.innerHTML = html;
}
function pop(x, y, text){
  var el = document.createElement("div");
  el.className = "pop"; el.textContent = text;
  el.style.left = x + "px"; el.style.top = y + "px";
  document.body.appendChild(el);
  setTimeout(function(){ el.remove(); }, 950);
}
function burst(x, y, glyph){
  for (var i = 0; i < 10; i++){
    var b = document.createElement("div");
    b.className = "burst"; b.textContent = glyph;
    b.style.left = x + "px"; b.style.top = y + "px";
    b.style.setProperty("--dx", (Math.random() * 160 - 80) + "px");
    b.style.setProperty("--dy", (Math.random() * 160 - 80) + "px");
    document.body.appendChild(b);
    setTimeout(function(){ b.remove(); }, 720);
  }
}
function click(ev){
  var g = tapPower();
  S.bal += g; S.total += g; S.clicks += 1;
  var c = document.getElementById("tap");
  c.classList.remove("squash"); void c.offsetWidth; c.classList.add("squash");
  var x = ev && ev.clientX ? ev.clientX : window.innerWidth / 2;
  var y = ev && ev.clientY ? ev.clientY : window.innerHeight / 2;
  pop(x, y, "+" + fmt(g));
  numbers();
}
function buyN(id, count){
  var b = BUILDINGS.find(function(x){ return x.id === id; });
  var c = cost(b, count);
  if (S.bal < c) return;
  S.bal -= c; S.b[id] = own(id) + count;
  dirty = true; numbers(); lists();
  var row = document.querySelector('[data-buy="' + id + '"]');
  if (row){ row.classList.remove("flash"); void row.offsetWidth; row.classList.add("flash"); }
}
function buyTree(id){
  var t = TREE.find(function(x){ return x.id === id; });
  if (!t || treeHas(id) || S.chips < t.cost) return;
  S.chips -= t.cost; S.tree.push(id);
  dirty = true; numbers(); lists();
}
function buyUp(id){
  var u = UPGRADES.find(function(x){ return x.id === id; });
  if (!u || has(id) || S.bal < u.cost) return;
  S.bal -= u.cost; S.u.push(id);
  dirty = true; numbers(); lists();
}
function ascend(){
  var gain = Math.floor(Math.cbrt(S.total / 1e6));
  if (gain < 1){ toast("Нужно ~1e6 югов за всё время"); return; }
  S.chips += gain; S.resets += 1;
  S.bal = 0; S.total = 0; S.b = {}; S.u = []; S.clicks = 0;
  buffs = []; dirty = true;
  toast("Вознесение! +" + gain + " фишек");
  numbers(); lists();
}
function resetAll(){
  localStorage.removeItem(KEY);
  S = {bal:0,total:0,clicks:0,golden:0,chips:0,resets:0,b:{},u:[],tree:[],tab:"b"};
  buffs = []; dirty = true;
  numbers(); lists(); toast("Сброшено");
}
function spawnGolden(){
  var g = document.getElementById("gold");
  g.style.left = (12 + Math.random() * 65) + "vw";
  g.style.top = (18 + Math.random() * 55) + "vh";
  g.style.display = "block";
  setTimeout(function(){ g.style.display = "none"; }, 13000);
}
function catchGolden(ev){
  document.getElementById("gold").style.display = "none";
  burst(ev && ev.clientX ? ev.clientX : window.innerWidth / 2,
        ev && ev.clientY ? ev.clientY : window.innerHeight / 2, "🍪");
  S.golden += 1;
  var r = Math.random();
  if (r < .45){ addBuff("frenzy", 77000); toast("🍪 FRENZY ×7 на 77 сек"); }
  else if (r < .75){ addBuff("click", 13000); toast("⚡ CLICK FRENZY ×777 на 13 сек"); }
  else { var b = Math.max(50, cps() * 900); S.bal += b; S.total += b; toast("🍪 LUCKY +" + fmt(b)); }
  numbers();
}
/* --- дешёвое обновление цифр, без перестройки DOM --- */
function numbers(){
  document.getElementById("bal").textContent = fmt(S.bal);
  document.getElementById("cpsl").textContent = "в секунду: " + fmt(cps());
  document.getElementById("tapv").textContent = "+" + fmt(tapPower()) + " за клик";
  document.getElementById("chipline").textContent = "фишек: " + S.chips;
  var bl = buffs.filter(function(b){ return b.until > Date.now(); });
  document.getElementById("buffs").innerHTML = bl.map(function(b){
    return '<div class="buff">' + (b.kind === "frenzy" ? "🔥 ×7" : "⚡ ×777") +
      " " + Math.ceil((b.until - Date.now()) / 1000) + "с</div>";
  }).join("");
  document.getElementById("ascinfo").textContent =
    "вознесение: +" + Math.max(0, Math.floor(Math.cbrt(S.total / 1e6))) +
    " фишек · сбросов " + S.resets;
}
/* --- полная перестройка списков: только при покупке/смене вкладки --- */
function lists(){
  if (!dirty) return;
  dirty = false;
  var owned = BUILDINGS.filter(function(b){ return own(b.id) > 0; });
  document.getElementById("streets").innerHTML = owned.length
    ? owned.map(function(b){
        var n = Math.min(own(b.id), 14);
        return '<div class="street"><div class="lbl">' + b.n + '</div>' +
          '<div class="num">×' + own(b.id) + '</div>' +
          '<div class="row2">' + b.e.repeat(n) + '</div></div>';
      }).join("")
    : '<div class="panel" style="padding:26px;text-align:center;color:#a98a5f;font-size:13px">' +
      'Купи первое здание справа</div>';

  var box = document.getElementById("shop");
  if (S.tab === "b"){
    box.innerHTML = BUILDINGS.map(function(b){
      var c = cost(b, 1), can = S.bal >= c;
      return '<div class="item' + (can ? "" : " off") + '" data-buy="' + b.id + '">' +
        '<div class="ic">' + b.e + '</div><div class="tx"><div class="nm">' + b.n +
        '</div><div class="pr">' + fmt(c) + '</div></div>' +
        '<div class="ct">' + own(b.id) + '</div></div>';
    }).join("");
  } else if (S.tab === "u"){
    box.innerHTML = treeSVG();
  } else {
    box.innerHTML = '<div style="padding:10px;display:flex;flex-wrap:wrap;gap:5px">' +
      ACH.map(function(a){
        return '<span style="font-size:10px;padding:4px 8px;border-radius:7px;border:1px solid ' +
          (a.check() ? "#8bd65a" : "#5a3a1e") + ';color:' + (a.check() ? "#8bd65a" : "#7a5a38") +
          '">' + a.n + '</span>';
      }).join("") + '</div>';
  }
}
/* делегирование: обработчики не теряются при перестройке */
document.getElementById("shop").addEventListener("click", function(e){
  var t = e.target.closest("[data-buy],[data-up],[data-tree]");
  if (!t) return;
  if (t.dataset.buy) buyN(t.dataset.buy, 1);
  else if (t.dataset.tree) buyTree(t.dataset.tree);
  else buyUp(t.dataset.up);
});
document.getElementById("tabs").addEventListener("click", function(e){
  var b = e.target.closest("[data-tab]");
  if (!b) return;
  if (b.dataset.tab === "u"){ openTree(); return; }
  S.tab = b.dataset.tab;
  document.querySelectorAll("#tabs [data-tab]").forEach(function(x){
    x.className = x === b ? "on" : "";
  });
  dirty = true; lists();
});
document.getElementById("tap").onclick = click;
document.getElementById("tmclose").onclick = closeTree;
(function(){
  var body = document.getElementById("tmb");
  body.addEventListener("pointerdown", function(e){
    pan.drag = true; pan.moved = 0;
    pan.sx = e.clientX; pan.sy = e.clientY;
    pan.ox = pan.x; pan.oy = pan.y;
  });
  window.addEventListener("pointermove", function(e){
    if (!pan.drag) return;
    var dx = e.clientX - pan.sx, dy = e.clientY - pan.sy;
    pan.moved = Math.max(pan.moved, Math.abs(dx) + Math.abs(dy));
    pan.x = pan.ox + dx; pan.y = pan.oy + dy;
    applyPan();
  });
  window.addEventListener("pointerup", function(e){
    if (!pan.drag) return;
    pan.drag = false;
    if (pan.moved < 8){
      var t = e.target.closest("[data-tree]");
      if (t) buyTree(t.dataset.tree);
    }
  });
})();
document.getElementById("ascend").onclick = ascend;
document.getElementById("reset").onclick = resetAll;
document.getElementById("gold").onclick = catchGolden;
try { var raw = localStorage.getItem(KEY); if (raw) S = Object.assign(S, JSON.parse(raw)); } catch(e){}
setInterval(function(){
  var g = cps() / 10;
  S.bal += g; S.total += g;
  var before = buffs.length;
  buffs = buffs.filter(function(b){ return b.until > Date.now(); });
  numbers();
}, 100);
/* раз в 2 сек — обновить цены и «доступность» в магазине */
setInterval(function(){ dirty = true; lists(); }, 2000);
setInterval(function(){ if (Math.random() < .5) spawnGolden(); }, 45000);
setInterval(function(){ try { localStorage.setItem(KEY, JSON.stringify(S)); } catch(e){} }, 4000);
numbers(); lists(); makeParticles();
</script>
</body>
</html>
"""


@router.get("/proto_yugi", response_class=HTMLResponse)
async def proto_yugi() -> HTMLResponse:
    """Прототип кликера: чистая симуляция в браузере, база не затрагивается."""
    return HTMLResponse(PROTO_PAGE)
DUNGEON_PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>Прототип · Подземелье Тимура</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
@import url("https://fonts.googleapis.com/css2?family=Press+Start+2P&display=swap");
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent;user-select:none}
html,body{margin:0;height:100dvh;overflow:hidden;background:#07060a;
  font-family:"Press Start 2P",ui-monospace,monospace;color:#e6dcc8;
  image-rendering:pixelated;font-size:11px;line-height:1.5}
#cv{display:block;width:100%;height:100%;touch-action:none;background:#0d0a10;
  image-rendering:pixelated}
.top{position:fixed;top:0;left:0;right:0;display:flex;gap:6px;padding:8px;
  background:linear-gradient(#0b0e14ee,#0b0e1400);z-index:10}
.top{justify-content:space-between;background:none}
.top .grp{display:flex;gap:7px}
.top button{border:0;color:#f0d79a;border-radius:50%;width:46px;height:46px;
  font-size:18px;font-family:inherit;padding:0;
  background:url(/static/ui/btn_yellow.png) center/100% 100% no-repeat;
  filter:drop-shadow(0 3px 6px #000a)}
.top button:active{transform:translateY(2px)}
#wpanel{position:fixed;left:8px;right:8px;bottom:8px;display:flex;gap:8px;
  z-index:10}
.wcol{flex:1;min-width:0;background:linear-gradient(#2a1c10ee,#140d06ee);border:3px solid #6b4a22;
  border-radius:10px;padding:8px 10px;box-shadow:0 0 0 2px #120c06}
.wttl{font-size:7px;letter-spacing:1px;color:#c9a227;margin-bottom:5px}
.wname{font-size:9px;color:#ffe9b8;line-height:1.4}
.wsub{font-size:7px;color:#8a7a5a;margin-top:3px}
.wstat{display:flex;justify-content:space-between;font-size:7px;color:#b8a888;
  padding:2px 0}
.wstat b{color:#8bd65a}
.hpbar{position:fixed;left:14px;right:14px;bottom:244px;height:15px;z-index:13;
  background:#000a;border:2px solid #2a3346;border-radius:99px;overflow:hidden;z-index:10}
.hpbar i{display:block;height:100%;background:linear-gradient(#4ade80,#16a34a);
  transition:width .2s;width:100%}
.hptxt{position:fixed;left:0;right:0;bottom:262px;text-align:center;font-size:11px;
  font-weight:900;color:#fff;text-shadow:0 1px 4px #000;z-index:10;
  font-family:ui-monospace,monospace}
.joy{position:fixed;left:14px;bottom:112px;width:118px;height:118px;border-radius:50%;
  background:radial-gradient(circle at 35% 30%,#2a1e12,#120c06);
  border:3px solid #6b4a22;z-index:11;touch-action:none;
  box-shadow:0 0 0 3px #120c06,inset 0 0 22px #000000cc,0 0 18px #00000088}
.joy::after{content:"";position:absolute;inset:14px;border-radius:50%;
  border:2px dashed #6b4a2255}
.joy i{position:absolute;left:50%;top:50%;width:62px;height:62px;margin:-31px 0 0 -31px;
  border-radius:50%;background:radial-gradient(circle at 35% 30%,#5a4020,#241608);
  border:3px solid #c9a227;box-shadow:0 0 12px #000000aa,inset 0 0 8px #00000088}
.btns{position:fixed;right:14px;bottom:112px;display:flex;align-items:flex-end;gap:10px;z-index:11}
.ab{width:62px;height:62px;border:0;border-radius:50%;color:#f0d79a;
  font-size:24px;font-family:inherit;position:relative;
  display:flex;align-items:center;justify-content:center;
  background:url(/static/ui/btn_grey.png) center/100% 100% no-repeat;
  filter:drop-shadow(0 3px 6px #000a)}
.ab:active{transform:translateY(2px);filter:drop-shadow(0 1px 3px #000a)}
.ab.atk{width:80px;height:80px;color:#ffd0c0;font-size:28px;
  background:url(/static/ui/btn_red.png) center/100% 100% no-repeat}
.ab .cd{position:absolute;inset:-3px;border-radius:50%;background:#000a;display:none;
  align-items:center;justify-content:center;font-size:13px;font-weight:900}
.ab.cool .cd{display:flex}
.coins{position:fixed;top:52px;right:12px;background:#151a25dd;border:1px solid #2a3346;
  border-radius:9px;padding:6px 11px;font-size:12px;font-weight:900;color:#f6c94a;z-index:10;
  font-family:ui-monospace,monospace}
.cls{position:fixed;inset:0;background:#0b0e14f2;z-index:30;display:flex;
  flex-direction:column;align-items:center;justify-content:center;gap:14px;padding:20px}
.cls h1{margin:0 0 6px;font-size:20px}
.cls .c{width:100%;max-width:360px;border:2px solid #2a3346;background:#151a25;
  border-radius:14px;padding:14px;text-align:left;color:#e8ebf2;font-family:inherit}
.cls .c b{font-size:15px}
.cls .c span{display:block;font-size:11.5px;color:#8b93a7;margin-top:3px}
#bag{position:fixed;inset:0;background:#0b0e14f8;z-index:80;display:none;
  flex-direction:column}
#bag.on{display:flex}
#battle{position:fixed;inset:0;background:#0b0e14f6;z-index:40;display:none;
  flex-direction:column;padding:14px}
#battle.on{display:flex}
.arena{flex:1;display:flex;align-items:center;justify-content:space-between;gap:10px}
.fighter{width:44%;text-align:center}
.fighter canvas{width:100%;height:190px}
.fname{font-size:12px;font-weight:900;margin-top:6px}
.fhp{height:14px;background:#000a;border:2px solid #2a3346;border-radius:99px;
  overflow:hidden;margin-top:5px}
.fhp i{display:block;height:100%;background:linear-gradient(#4ade80,#16a34a);width:100%;
  transition:width .15s}
.acts{display:flex;gap:10px;justify-content:center;padding-bottom:6px}
#fx{position:fixed;inset:0;width:100%;height:100%;z-index:6;pointer-events:none;
  display:block;opacity:0;transition:opacity .35s;background:transparent}
body.fxon #fx{opacity:1}
#gfx{position:fixed;inset:0;z-index:90;display:none;align-items:center;justify-content:center;
  background:#07060aee;padding:18px}
#gfx.on{display:flex}
#gfx .card{width:100%;max-width:340px;border:3px solid #6b4a22;border-radius:12px;
  background:linear-gradient(#241708,#120b06);padding:14px;box-shadow:0 0 0 3px #120c06}
#gfx h3{margin:0 0 10px;font-size:10px;color:#ffd98a;letter-spacing:1px}
#gfx button{display:block;width:100%;margin:6px 0;padding:10px;border-radius:8px;
  border:2px solid #6b4a22;background:#2a1c10;color:#ffe9b8;font-family:inherit;
  font-size:9px;text-align:left;line-height:1.5}
#gfx button.on{border-color:#c9a227;background:#3a2a12;color:#fff}
#gfx .fps{margin-top:8px;font-size:7px;color:#8a7a5a;line-height:1.6}
/* подсказка, если страницу открыли не как мини-аппку */
#tghint{position:fixed;top:96px;left:50%;transform:translateX(-50%);z-index:9;
  font-size:7px;line-height:1.5;color:#ffb4b4;background:#2a0e12ee;
  border:1px solid #6b1a22;border-radius:8px;padding:5px 9px;
  pointer-events:none;text-align:center;max-width:80vw}
/* таблица лидеров */
#top{position:fixed;inset:0;z-index:52;display:none;flex-direction:column;
  align-items:center;justify-content:flex-start;padding:18px 14px;background:#07060af0;
  overflow-y:auto}
#top.on{display:flex}
.tpwrap{width:100%;max-width:420px;border:3px solid #2a3346;border-radius:12px;
  background:#0d1016f2;padding:12px;display:flex;flex-direction:column;gap:8px}
.tphead{display:flex;justify-content:space-between;align-items:center;
  font-size:8px;color:#c9a227;letter-spacing:1px}
.tphead button{border:0;background:none;color:#8a7a5a;font-size:14px;
  font-family:inherit;padding:0 4px}
.tplist{display:flex;flex-direction:column;gap:6px}
.tprow{display:flex;justify-content:space-between;align-items:center;gap:8px;
  border:1px solid #1e2530;border-radius:9px;padding:8px 10px;background:#151a25}
.tprow.mine{border-color:#3b6fff;box-shadow:0 0 12px #3b6fff33}
.tprow b{font-size:9px;color:#ffe9b8;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
.tprow span{font-size:7px;color:#8a7a5a;font-family:ui-monospace,monospace;
  white-space:nowrap}
.tprow i{font-style:normal;color:#c9a227;font-size:8px;width:18px}
/* чат подземелья */
#chat{position:fixed;inset:0;z-index:50;display:none;flex-direction:column;
  align-items:center;justify-content:flex-end;padding:14px;background:#07060ad8}
#chat.on{display:flex}
.chwrap{width:100%;max-width:420px;border:3px solid #2a3346;border-radius:12px;
  background:#0d1016f2;padding:10px;display:flex;flex-direction:column;gap:8px}
.chhead{display:flex;justify-content:space-between;align-items:center;
  font-size:8px;color:#c9a227;letter-spacing:1px}
.chhead button{border:0;background:none;color:#8a7a5a;font-size:14px;
  font-family:inherit;padding:0 4px}
.chlog{height:210px;overflow-y:auto;font-size:9px;line-height:1.7;
  color:#c9d3e3;font-family:ui-monospace,monospace;display:flex;
  flex-direction:column;gap:3px}
.chlog b{color:#ffd98a}
.chin{display:flex;gap:8px}
.chin input{flex:1;min-width:0;border:2px solid #2a3346;border-radius:9px;
  background:#151a25;color:#e8ebf2;font-family:inherit;font-size:10px;padding:9px}
.chin button{width:52px;border:0;border-radius:9px;color:#fff;font-size:14px;
  background:linear-gradient(#3b6fff,#22409e);font-family:inherit}
/* кооп-босс: общий бой на двоих */
#coop{position:fixed;inset:0;z-index:45;display:none;flex-direction:column;
  align-items:center;justify-content:center;padding:14px;
  background:radial-gradient(circle at 50% 28%,#1c0d12f2,#07060af8)}
#coop.on{display:flex}
.cwrap{width:100%;max-width:420px;display:flex;flex-direction:column;gap:9px}
.chead{display:flex;justify-content:space-between;font-size:8px;color:#c9a227;
  letter-spacing:1px}
.cboss{border:3px solid #6b1a22;border-radius:12px;padding:10px;
  background:linear-gradient(#230e12ee,#120709ee);box-shadow:0 0 24px #ff3b5244}
.cnm{font-size:11px;color:#ffb4b4;margin-bottom:7px}
.cbar{height:16px;border-radius:99px;background:#000a;border:2px solid #4a1a20;
  overflow:hidden}
.cbar i{display:block;height:100%;width:100%;transition:width .25s;
  background:linear-gradient(#ff7a3c,#c81e2e)}
.chpt{font-size:8px;color:#ffd0a0;margin-top:6px;font-family:ui-monospace,monospace}
.cteam{display:flex;gap:8px}
.cp{flex:1;min-width:0;border:2px solid #2a3346;border-radius:10px;padding:8px;
  background:#151a25dd}
.cp.mine{border-color:#3b6fff;box-shadow:0 0 14px #3b6fff44}
.cp.out{opacity:.4}
.cp b{display:block;font-size:9px;color:#ffe9b8;margin-bottom:6px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cp .bar{height:11px;border-radius:99px;background:#000a;border:1px solid #2a3346;
  overflow:hidden}
.cp .bar i{display:block;height:100%;background:linear-gradient(#4ade80,#16a34a);
  transition:width .2s}
.cp span{display:block;font-size:7px;color:#8a7a5a;margin-top:5px;
  font-family:ui-monospace,monospace}
.clog{height:92px;overflow:hidden;border:2px solid #2a3346;border-radius:10px;
  background:#0d1016cc;padding:8px;font-size:8px;line-height:1.7;color:#9aa4b8;
  font-family:ui-monospace,monospace}
.clog b{color:#ffd98a}
.cact{display:flex;gap:10px}
.cact button{flex:1;height:56px;border:0;border-radius:14px;font-family:inherit;
  font-size:12px;color:#fff;background:linear-gradient(#c81e2e,#7a121c);
  box-shadow:0 4px 0 #3a0a10;transition:transform .06s}
.cact button:active{transform:translateY(3px);box-shadow:0 1px 0 #3a0a10}
.cact button.leave{flex:0 0 92px;background:linear-gradient(#2a3346,#161c28);
  box-shadow:0 4px 0 #0b0f16;font-size:10px;color:#9aa4b8}
.cact button:disabled{opacity:.45;box-shadow:0 4px 0 #000a}
/* перебиваем общий стиль темы: он тянет тост на всю ширину */
body #toast{position:fixed!important;left:50%!important;right:auto!important;
  width:auto!important;max-width:76vw;bottom:304px;
  background:#1a1410f5;color:#ffe9b8;border:2px solid #6b4a22;
  border-radius:8px;padding:7px 12px;font-size:7px;line-height:1.5;
  text-align:center;transform:translate(-50%,320%);transition:.22s;z-index:60;
  box-shadow:0 0 0 2px #120c06,0 6px 16px #000000aa;animation:none!important}
body #toast.on{transform:translate(-50%,0)!important;animation:none!important}
/* переключатель разделов мини-аппки */
.apps{position:fixed;top:54px;left:50%;transform:translateX(-50%);z-index:9;
  display:flex;gap:4px;background:#120d0af0;border:2px solid #6b4a22;
  border-radius:999px;padding:3px}
.apps a{font-family:inherit;font-size:8px;color:#c9a227;text-decoration:none;
  padding:6px 8px;border-radius:999px;white-space:nowrap;line-height:1}
.apps a.on{background:#ffd98a;color:#1b1206}
</style>
</head>
<body>
<canvas id="cv"></canvas>
<canvas id="fx"></canvas>

<div class="top">
  <div class="grp">
    <button data-tab="clicker" title="В кликер">◀</button>
    <button data-tab="bag" title="Сумка">🎒</button>
    <button data-tab="quests" title="Задания">📜</button>
  </div>
  <div class="grp">
    <button data-tab="board" title="Лидерборд">👤</button>
    <button data-tab="settings" title="Настройки">⚙</button>
  </div>
</div>
<nav class="apps">
  <a href="/yugi">🍁 Кликер</a>
  <a class="on" href="/proto_dungeon">🗡 Подземелье</a>
  <a href="/quests">📜 Задания</a>
</nav>
<div class="coins">🪙 <span id="coins">0</span></div>
<div id="zone" style="position:fixed;top:8px;left:50%;transform:translateX(-50%);
  z-index:9;font-size:8px;color:#d8b45a;text-shadow:0 2px 6px #000;pointer-events:none">…</div>
<button id="bagbtn" style="position:fixed;top:92px;left:12px;z-index:25;
  background:#161020dd;border:2px solid #3a2a4a;color:#cbb9d6;border-radius:8px;
  padding:8px 12px;font-family:inherit;font-size:10px">🎒 СУМКА</button>

<div id="wpanel">
  <div class="wcol">
    <div class="wttl">ОРУЖИЕ</div>
    <div class="wname" id="wname">—</div>
    <div class="wsub" id="wcls">—</div>
  </div>
  <div class="wcol">
    <div class="wttl">СТАТИСТИКА ОРУЖИЯ</div>
    <div class="wstat"><span>Урон</span><b id="wdmg">0</b></div>
    <div class="wstat"><span>Дальность</span><b id="wrange">0</b></div>
    <div class="wstat"><span>Скорость</span><b id="wspd">0</b></div>
    <div style="display:flex;gap:6px;margin-top:6px">
      <button id="warmor" style="width:100%;border:2px solid #6b4a22;background:#2a1c10;
        color:#9fd6ff;border-radius:6px;padding:6px 0;font-family:inherit;font-size:7px;
        margin-bottom:6px">БРОНЯ</button>
      <button id="wupg" style="flex:1;border:2px solid #6b4a22;background:#2a1c10;
        color:#c9a227;border-radius:6px;padding:6px 0;font-family:inherit;font-size:7px">УЛУЧШИТЬ</button>
      <button id="wchat" style="flex:1;border:2px solid #6b4a22;background:#2a1c10;
        color:#c9a227;border-radius:6px;padding:6px 0;font-family:inherit;font-size:7px">ЧАТ</button>
    </div>
  </div>
</div>
<div class="hpbar"><i id="hpfill"></i></div>
<div class="hptxt" id="hptxt">HP 120 / 120</div>

<div class="joy" id="joy"><i id="knob"></i></div>
<div class="btns" style="left:50%;transform:translateX(-50%);right:auto;bottom:150px">
  <button class="ab" id="bag2" style="width:52px;height:52px;font-size:18px">🎒</button>
</div>
<div class="btns">
  <button class="ab" id="shield">💨<span class="cd" id="cdShield"></span></button>
  <button class="ab" id="ability">✋<span class="cd" id="cdAbility"></span></button>
  <button class="ab atk" id="attack">⚔<span class="cd" id="cdAttack"></span></button>
</div>

<div class="cls" id="cls">
  <h1>Подземелье Тимура</h1>
  <div style="font-size:12px;color:#8b93a7;max-width:360px;text-align:center;
    line-height:1.5">Класс не выбирается. Он зависит от того, что у тебя в руках:
    меч — мечник, лук — лучник, посох — маг.</div>
  <div id="inv" style="width:100%;max-width:360px;max-height:46vh;overflow:auto"></div>
  <button class="c" id="startbtn" style="text-align:center;border-color:#3b6fff">
    <b>Войти в подземелье</b></button>
</div>

<div id="bag"><div class="tmhead"><span>🎒 Сумка</span>
<button id="bagclose">Закрыть</button></div>
<div id="inv2" style="padding:12px;overflow:auto;flex:1"></div></div>

<div id="battle">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <div style="font-size:13px;font-weight:900" id="bname">БОСС</div>
    <button id="bflee" style="border:1px solid #2a3346;background:#151a25;color:#8b93a7;
      border-radius:9px;padding:8px 14px;font-family:inherit;font-size:12px">Сдаться</button>
  </div>
  <div class="arena">
    <div class="fighter">
      <canvas id="pcv" width="200" height="220"></canvas>
      <div class="fname">ИГРОК</div>
      <div class="fhp"><i id="php"></i></div>
    </div>
    <div class="fighter">
      <canvas id="ecv" width="200" height="220"></canvas>
      <div class="fname" id="ename">БОСС</div>
      <div class="fhp"><i id="ehp"></i></div>
    </div>
  </div>
  <div class="acts">
    <button class="ab" id="bshield">🛡</button>
    <button class="ab" id="bability">✋</button>
    <button class="ab atk" id="battack">⚔</button>
  </div>
</div>

<div id="coop">
  <div class="cwrap">
    <div class="chead"><span id="czone">ЛОКАЦИЯ</span><span id="cstat">ОЖИДАНИЕ</span></div>
    <div class="cboss">
      <div class="cnm" id="cname">БОСС</div>
      <div class="cbar"><i id="cbhp"></i></div>
      <div class="chpt" id="cbhpt">…</div>
    </div>
    <div class="cteam" id="cteam"></div>
    <div class="clog" id="clog"></div>
    <div class="cact">
      <button id="chit">⚔ УДАР</button>
      <button id="cleave" class="leave">ВЫЙТИ</button>
    </div>
  </div>
</div>
<div id="top">
  <div class="tpwrap">
    <div class="tphead"><span>ЛИДЕРЫ ПОДЗЕМЕЛЬЯ</span><button id="tpclose">✕</button></div>
    <div class="tplist" id="tplist"></div>
  </div>
</div>
<div id="chat">
  <div class="chwrap">
    <div class="chhead"><span>ЧАТ ПОДЗЕМЕЛЬЯ</span><button id="chclose">✕</button></div>
    <div class="chlog" id="chlog"></div>
    <div class="chin">
      <input id="chtext" maxlength="80" placeholder="сообщение…">
      <button id="chsend">→</button>
    </div>
  </div>
</div>
<div id="toast"></div>
<div id="gfx"></div>
<script>
const cv = document.getElementById("cv"), ctx = cv.getContext("2d");
/* ---------- FX: шейдерная постобработка, bloom, частицы ---------- */
const FXCV = document.getElementById("fx");
const FX = (function(){
  const SPR = {}, ps = [], ds = [];
  let ambientT = 0, hurtCd = 0, swing = null, fpsAcc = 0, fpsN = 0, lastAuto = 0;

  function hx(col, a){
    if (!col || col.charAt(0) !== "#" || col.length < 7) return col;
    const n = parseInt(col.slice(1, 7), 16);
    return "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + a + ")";
  }
  // спрайт свечения: белый центр, мягкий спад в цвете
  function sprite(col){
    if (SPR[col]) return SPR[col];
    const s = document.createElement("canvas");
    s.width = 64; s.height = 64;
    const c = s.getContext("2d");
    const g = c.createRadialGradient(32, 32, 0, 32, 32, 33);
    g.addColorStop(0, "rgba(255,255,255,0.92)");
    g.addColorStop(0.22, hx(col, 0.92));
    g.addColorStop(0.58, hx(col, 0.22));
    g.addColorStop(1, hx(col, 0));
    c.fillStyle = g;
    c.fillRect(0, 0, 64, 64);
    SPR[col] = s;
    return s;
  }
  function emit(x, y, o){
    if (ps.length > 420) ps.shift();
    const life = o.life || 0.5;
    ps.push({x: x, y: y, vx: o.vx || 0, vy: o.vy || 0,
      life: life, max: life, size: o.size || 10, col: o.col || "#ffd98a",
      grav: o.grav || 0, drag: (o.drag == null ? 2.2 : o.drag)});
  }
  function burst(x, y, n, col, spd, size){
    for (let i = 0; i < n; i++){
      const a = Math.random() * 6.2832, sp = spd * (0.3 + Math.random());
      emit(x, y, {vx: Math.cos(a) * sp, vy: Math.sin(a) * sp * 0.75 - spd * 0.12,
        life: 0.28 + Math.random() * 0.45, size: (size || 12) * (0.5 + Math.random()),
        col: col, drag: 3.4});
    }
  }
  function dust(x, y, n){
    for (let i = 0; i < n; i++){
      if (ds.length > 90) ds.shift();
      const life = 0.3 + Math.random() * 0.35;
      ds.push({x: x + (Math.random() - 0.5) * 12, y: y + Math.random() * 4,
        vx: (Math.random() - 0.5) * 26, vy: -6 - Math.random() * 14,
        life: life, max: life, size: 2 + Math.random() * 3});
    }
  }
  function glowAt(x, y, size, col, alpha){
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    ctx.globalAlpha = (alpha == null ? 0.85 : alpha);
    ctx.drawImage(sprite(col), x - size / 2, y - size / 2, size, size);
    ctx.restore();
  }

  function step(dt){
    if (hurtCd > 0) hurtCd -= dt;
    if (swing){ swing.t -= dt; if (swing.t <= 0) swing = null; }
    for (let i = ps.length - 1; i >= 0; i--){
      const p = ps[i];
      p.life -= dt;
      if (p.life <= 0){ ps.splice(i, 1); continue; }
      p.vy += p.grav * dt;
      const d = Math.max(0, 1 - p.drag * dt);
      p.vx *= d; p.vy *= d;
      p.x += p.vx * dt; p.y += p.vy * dt;
    }
    for (let i = ds.length - 1; i >= 0; i--){
      const p = ds[i];
      p.life -= dt;
      if (p.life <= 0){ ds.splice(i, 1); continue; }
      p.vy += 24 * dt;
      p.x += p.vx * dt; p.y += p.vy * dt;
    }
    if (api.flash > 0) api.flash = Math.max(0, api.flash - dt * 2.6);
    if (api.shakeT > 0){
      api.shakeT -= dt;
      const k = Math.max(0, api.shakeT / Math.max(0.001, api.shakeLen));
      api.shakeX = (Math.random() * 2 - 1) * api.shakeA * k;
      api.shakeY = (Math.random() * 2 - 1) * api.shakeA * k;
    } else if (api.shakeX || api.shakeY){ api.shakeX = 0; api.shakeY = 0; }
  }

  function draw(){
    if (swing){
      const k = Math.max(0, swing.t / 0.18);
      const col = swing.kind === "bow" ? "#8bd65a" : swing.kind === "staff" ? "#8fd8ff" : "#ffd98a";
      ctx.save();
      ctx.translate(P.x, P.y - 8);
      ctx.rotate(swing.a || 0);
      ctx.globalCompositeOperation = "lighter";
      ctx.lineCap = "round";
      ctx.strokeStyle = col;
      ctx.globalAlpha = k * 0.95;
      ctx.lineWidth = 3 + 9 * k;
      ctx.beginPath(); ctx.arc(0, 0, 40, -0.85, 0.85); ctx.stroke();
      ctx.globalAlpha = k * 0.4;
      ctx.lineWidth = 16 * k;
      ctx.beginPath(); ctx.arc(0, 0, 33, -0.7, 0.7); ctx.stroke();
      ctx.restore();
    }
    if (ds.length){
      ctx.save();
      for (let i = 0; i < ds.length; i++){
        const p = ds[i], k = Math.max(0, p.life / p.max);
        ctx.fillStyle = "rgba(128,112,80," + (0.32 * k) + ")";
        ctx.fillRect(p.x - p.size / 2, p.y - p.size / 2, p.size, p.size);
      }
      ctx.restore();
    }
    if (ps.length){
      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      for (let i = 0; i < ps.length; i++){
        const p = ps[i], k = Math.max(0, p.life / p.max);
        ctx.globalAlpha = Math.min(1, 0.14 + k * 1.2);
        const s = p.size * (0.5 + k * 0.9) * 2;
        ctx.drawImage(sprite(p.col), p.x - s / 2, p.y - s / 2, s, s);
      }
      ctx.restore();
    }
  }

  function ambient(dt, cx, cy, vw, vh){
    ambientT -= dt;
    if (ambientT > 0) return;
    ambientT = 0.055;
    const z = ZONES[zoneIndex(P.y)];
    emit(cx + Math.random() * vw, cy + Math.random() * vh,
      {vx: (Math.random() - 0.5) * 14, vy: -10 - Math.random() * 26,
       life: 1.6 + Math.random() * 2.4, size: 2 + Math.random() * 6,
       col: z.a, drag: 0.15});
  }

  function shake(a){
    api.shakeA = Math.max(api.shakeA * 0.6, a);
    api.shakeT = api.shakeLen = 0.22;
  }
  function hurt(){
    if (hurtCd > 0) return;
    hurtCd = 0.32;
    api.flash = Math.min(0.55, api.flash + 0.4);
    shake(5);
    burst(P.x, P.y - 10, 6, "#ff3b52", 120, 10);
  }

  /* ---------- WebGL ---------- */
  let gl = null;
  try {
    gl = FXCV.getContext("webgl", {alpha: false, antialias: false, depth: false,
      stencil: false, premultipliedAlpha: false, powerPreference: "high-performance"});
  } catch (e){ gl = null; }

  let level = 2;
  try {
    const v = localStorage.getItem("dungeon_fx");
    if (v !== null) level = Math.max(0, Math.min(2, parseInt(v, 10) || 0));
  } catch (e){}
  if (!gl) level = 0;

  const VS = `
attribute vec2 a_pos;
varying vec2 v_uv;
void main(){
  v_uv = a_pos * 0.5 + 0.5;
  gl_Position = vec4(a_pos, 0.0, 1.0);
}
`;

  const FS_BRIGHT = `
precision mediump float;
varying vec2 v_uv;
uniform sampler2D u_tex;
uniform vec2 u_texel;
uniform float u_thr;
void main(){
  vec3 c = texture2D(u_tex, v_uv).rgb * 0.4;
  c += texture2D(u_tex, v_uv + vec2(u_texel.x, 0.0)).rgb * 0.15;
  c += texture2D(u_tex, v_uv - vec2(u_texel.x, 0.0)).rgb * 0.15;
  c += texture2D(u_tex, v_uv + vec2(0.0, u_texel.y)).rgb * 0.15;
  c += texture2D(u_tex, v_uv - vec2(0.0, u_texel.y)).rgb * 0.15;
  float l = max(c.r, max(c.g, c.b));
  float k = max(l - u_thr, 0.0) / max(l, 0.001);
  k = k * k;
  gl_FragColor = vec4(c * k * 2.3, 1.0);
}
`;

  const FS_BLUR = `
precision mediump float;
varying vec2 v_uv;
uniform sampler2D u_tex;
uniform vec2 u_dir;
void main(){
  vec3 s = texture2D(u_tex, v_uv).rgb * 0.227027;
  s += texture2D(u_tex, v_uv + u_dir * 1.3846).rgb * 0.3162162;
  s += texture2D(u_tex, v_uv - u_dir * 1.3846).rgb * 0.3162162;
  s += texture2D(u_tex, v_uv + u_dir * 3.2308).rgb * 0.0702703;
  s += texture2D(u_tex, v_uv - u_dir * 3.2308).rgb * 0.0702703;
  gl_FragColor = vec4(s, 1.0);
}
`;

  const FS_COPY = `
precision mediump float;
varying vec2 v_uv;
uniform sampler2D u_tex;
void main(){
  gl_FragColor = vec4(texture2D(u_tex, v_uv).rgb, 1.0);
}
`;

  const FS_FINAL = `
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
varying vec2 v_uv;
uniform sampler2D u_scene, u_b0, u_b1, u_b2;
uniform float u_time, u_flash, u_hp, u_grain, u_aberr;
uniform vec3 u_w;
uniform vec2 u_res;
void main(){
  vec2 uv = vec2(v_uv.x, 1.0 - v_uv.y);
  vec2 d = uv - 0.5;
  float r2 = dot(d, d);
  float ab = u_aberr * (0.0012 + r2 * 0.0085);
  vec3 col;
  col.r = texture2D(u_scene, uv + d * ab).r;
  col.g = texture2D(u_scene, uv).g;
  col.b = texture2D(u_scene, uv - d * ab).b;

  vec3 bl = texture2D(u_b0, uv).rgb * u_w.x + texture2D(u_b1, uv).rgb * u_w.y + texture2D(u_b2, uv).rgb * u_w.z;
  col += bl * 1.25;

  float l = dot(col, vec3(0.299, 0.587, 0.114));
  col = mix(vec3(l), col, 1.12);
  col = clamp((col - 0.42) * 1.16 + 0.42, 0.0, 1.0);

  col += vec3(0.012, 0.004, 0.026) * (1.0 - l);
  col *= vec3(1.04, 1.0, 1.02);

  float vig = 1.0 - smoothstep(0.26, 1.02, length(d) * 1.18);
  col *= mix(0.34, 1.0, vig);

  col = mix(col, col * vec3(1.6, 0.55, 0.55), u_flash);

  float danger = clamp(0.45 - u_hp, 0.0, 1.0) * 2.0;
  col = mix(col, vec3(0.55, 0.04, 0.06), danger * (1.0 - vig) * 0.55);

  float n = fract(sin(dot(uv * u_res + vec2(u_time * 37.0, u_time * 21.0), vec2(12.9898, 78.233))) * 43758.5453);
  col += (n - 0.5) * u_grain;

  gl_FragColor = vec4(col, 1.0);
}
`;

  let W = 0, H = 0, sceneTex = null, sceneW = 0, sceneH = 0, quad = null, PR = {}, LV = [];

  function compile(type, src){
    const s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS))
      throw new Error("shader: " + gl.getShaderInfoLog(s));
    return s;
  }
  function program(fs){
    const p = gl.createProgram();
    const vs = compile(gl.VERTEX_SHADER, VS);
    const f = compile(gl.FRAGMENT_SHADER, fs);
    gl.attachShader(p, vs);
    gl.attachShader(p, f);
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS))
      throw new Error("link: " + gl.getProgramInfoLog(p));
    return {p: p, a: gl.getAttribLocation(p, "a_pos"), u: {}};
  }
  function U(pr, name){
    if (!(name in pr.u)) pr.u[name] = gl.getUniformLocation(pr.p, name);
    return pr.u[name];
  }
  function makeTex(w, h){
    const t = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    return t;
  }
  function makeFBO(tex){
    const f = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, f);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    return f;
  }
  function allocLevels(w, h){
    for (let i = 0; i < LV.length; i++){
      gl.deleteTexture(LV[i].tex); gl.deleteTexture(LV[i].tex2);
      gl.deleteFramebuffer(LV[i].fbo); gl.deleteFramebuffer(LV[i].fbo2);
    }
    LV = [];
    for (let i = 0; i < 3; i++){
      const s = 1 << (i + 1);
      const lw = Math.max(4, Math.floor(w / s)), lh = Math.max(4, Math.floor(h / s));
      const a = makeTex(lw, lh), b = makeTex(lw, lh);
      LV.push({w: lw, h: lh, tex: a, fbo: makeFBO(a), tex2: b, fbo2: makeFBO(b)});
    }
  }
  function initGL(w, h){
    FXCV.width = w; FXCV.height = h;
    PR.bright = program(FS_BRIGHT);
    PR.blur = program(FS_BLUR);
    PR.copy = program(FS_COPY);
    PR.final = program(FS_FINAL);
    quad = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, quad);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    sceneTex = makeTex(w, h);
    sceneW = w; sceneH = h;
    allocLevels(w, h);
    gl.viewport(0, 0, w, h);
    gl.clearColor(0, 0, 0, 1);
    gl.clear(gl.COLOR_BUFFER_BIT);
  }
  function pass(pr, target, fn){
    gl.bindFramebuffer(gl.FRAMEBUFFER, target ? target.fbo : null);
    gl.viewport(0, 0, target ? target.w : W, target ? target.h : H);
    gl.useProgram(pr.p);
    gl.bindBuffer(gl.ARRAY_BUFFER, quad);
    gl.enableVertexAttribArray(pr.a);
    gl.vertexAttribPointer(pr.a, 2, gl.FLOAT, false, 0, 0);
    fn(pr);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }
  function unit(pr, name, tex, slot){
    gl.activeTexture(gl.TEXTURE0 + slot);
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.uniform1i(U(pr, name), slot);
  }
  function hpK(){
    const r = (P && P.max) ? (P.hp / P.max) : 1;
    return Math.max(0, Math.min(1, r));
  }

  function post(){
    if (!gl || level <= 0) return false;
    const w = cv.width, h = cv.height;
    if (!w || !h) return false;
    try {
      if (w !== W || h !== H){ W = w; H = h; initGL(w, h); }
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
      gl.disable(gl.BLEND);
      gl.bindTexture(gl.TEXTURE_2D, sceneTex);
      if (sceneW !== w || sceneH !== h){
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, cv);
        sceneW = w; sceneH = h;
      } else {
        gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, gl.RGBA, gl.UNSIGNED_BYTE, cv);
      }
      pass(PR.bright, LV[0], function(pr){
        unit(pr, "u_tex", sceneTex, 0);
        gl.uniform2f(U(pr, "u_texel"), 1 / w, 1 / h);
        gl.uniform1f(U(pr, "u_thr"), level > 1 ? 0.56 : 0.68);
      });
      const n = level > 1 ? 3 : 2;
      for (let i = 0; i < n; i++){
        const lv = LV[i];
        if (i > 0){
          pass(PR.copy, lv, function(pr){ unit(pr, "u_tex", LV[i - 1].tex, 0); });
        }
        pass(PR.blur, {w: lv.w, h: lv.h, fbo: lv.fbo2}, function(pr){
          unit(pr, "u_tex", lv.tex, 0);
          gl.uniform2f(U(pr, "u_dir"), 1.4 / lv.w, 0);
        });
        pass(PR.blur, lv, function(pr){
          unit(pr, "u_tex", lv.tex2, 0);
          gl.uniform2f(U(pr, "u_dir"), 0, 1.4 / lv.h);
        });
      }
      pass(PR.final, null, function(pr){
        unit(pr, "u_scene", sceneTex, 0);
        unit(pr, "u_b0", LV[0].tex, 1);
        unit(pr, "u_b1", LV[1].tex, 2);
        unit(pr, "u_b2", LV[2].tex, 3);
        gl.uniform1f(U(pr, "u_time"), (performance.now() / 1000) % 12);
        gl.uniform1f(U(pr, "u_flash"), api.flash);
        gl.uniform1f(U(pr, "u_hp"), hpK());
        gl.uniform1f(U(pr, "u_grain"), api.noise);
        gl.uniform1f(U(pr, "u_aberr"), api.aberr);
        gl.uniform3f(U(pr, "u_w"), 0.55, n > 2 ? 0.8 : 1.0, n > 2 ? 1.1 : 0.0);
        gl.uniform2f(U(pr, "u_res"), W, H);
      });
      if (!api.live){ api.live = true; document.body.classList.add("fxon"); }
      return true;
    } catch (e){
      gl = null;
      level = 0;
      api.level = 0;
      api.live = false;
      document.body.classList.remove("fxon");
      toast("Видео не тянет шейдеры — включил 2D-режим");
      return false;
    }
  }

  /* ---------- запасной bloom на Canvas2D ---------- */
  const fbA = document.createElement("canvas"), fbB = document.createElement("canvas");
  function bloom2d(){
    const w = cv.width, h = cv.height;
    if (!w || !h) return false;
    const aw = Math.max(4, w >> 2), ah = Math.max(4, h >> 2);
    const bw = Math.max(4, w >> 3), bh = Math.max(4, h >> 3);
    if (fbA.width !== aw || fbA.height !== ah){ fbA.width = aw; fbA.height = ah; }
    if (fbB.width !== bw || fbB.height !== bh){ fbB.width = bw; fbB.height = bh; }
    const ac = fbA.getContext("2d");
    ac.clearRect(0, 0, aw, ah);
    ac.drawImage(cv, 0, 0, aw, ah);
    const bc = fbB.getContext("2d");
    bc.clearRect(0, 0, bw, bh);
    bc.drawImage(fbA, 0, 0, bw, bh);
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    ctx.globalAlpha = 0.42;
    ctx.drawImage(fbA, 0, 0, w, h);
    ctx.globalAlpha = 0.34;
    ctx.drawImage(fbB, 0, 0, w, h);
    ctx.restore();
    return true;
  }

  const api = {
    level: level, live: false, hasGL: !!gl, flash: 0, noise: 0.045, aberr: 1.0,
    shakeT: 0, shakeA: 0, shakeLen: 0.22, shakeX: 0, shakeY: 0, fps: 60,
    emit: emit, burst: burst, dust: dust, glowAt: glowAt, hurt: hurt, shake: shake,
    step: step, draw: draw, ambient: ambient, post: post, bloom2d: bloom2d,
    sprite: sprite,
    swingAt: function(a, kind){ swing = {t: 0.18, a: a || 0, kind: kind}; },
    isGL: function(){ return !!gl && level > 0; },
    setLevel: function(n){
      n = Math.max(0, Math.min(2, n | 0));
      if (!gl) n = 0;
      level = n;
      api.level = n;
      try { localStorage.setItem("dungeon_fx", String(n)); } catch (e){}
      if (n === 0){
        document.body.classList.remove("fxon");
        api.live = false;
      } else {
        W = 0; H = 0;
      }
      return n;
    },
    tick: function(dt){
      fpsAcc += dt; fpsN++;
      if (fpsN < 60) return;
      const avg = fpsAcc / fpsN * 1000;
      api.fps = Math.round(1000 / Math.max(1, avg));
      fpsAcc = 0; fpsN = 0;
      const now = performance.now();
      if (avg > 32 && api.level > 0 && now - lastAuto > 4000){
        lastAuto = now;
        const before = api.level;
        api.setLevel(before - 1);
        toast("Медленно (" + Math.round(avg) + " мс) — качество графики снижено");
      }
    }
  };
  return api;
})();

/* ---------- кооп-босс: один босс на двоих ---------- */
// Telegram Desktop иногда отдаёт пустой initData, хотя данные лежат в адресе
// строкой tgWebAppData=... Достаём оттуда — иначе кооп молча не работает.
function readInitData(){
  let raw = "";
  try {
    if (window.Telegram && Telegram.WebApp && Telegram.WebApp.initData){
      raw = Telegram.WebApp.initData;
    }
  } catch (e){}
  if (!raw){
    // Telegram Desktop иногда оставляет данные в адресе
    try {
      const url = String(location.hash || "") + "&" + String(location.search || "");
      const found = url.match(/tgWebAppData=([^&]+)/);
      if (found) raw = decodeURIComponent(found[1]);
    } catch (e){}
  }
  // При переходе между страницами мини-аппки hash теряется: держим копию,
  // иначе кооп и прогресс молча отваливаются в 401.
  try {
    if (raw) sessionStorage.setItem("tginit", raw);
    else raw = sessionStorage.getItem("tginit") || "";
  } catch (e){}
  return raw;
}
const TG_INIT = readInitData();
// Без этого Telegram не раскрывает мини-апп на весь экран.
(function(){
  try {
    if (window.Telegram && Telegram.WebApp){
      Telegram.WebApp.ready();
      if (Telegram.WebApp.expand) Telegram.WebApp.expand();
    }
  } catch (e){}
})();
// Открыли ссылкой в браузере — кооп не заработает, честно предупреждаем
// и показываем, что именно не пришло: по этой строке сразу видно причину.
(function(){
  if (TG_INIT || !document.body || !document.body.appendChild) return;
  const hasTg = !!window.Telegram;
  const platform = (hasTg && Telegram.WebApp && Telegram.WebApp.platform) || "нет";
  const hint = document.createElement("div");
  hint.id = "tghint";
  hint.textContent = "КООП НЕДОСТУПЕН · открой через /dungeon в боте" +
    " · TG:" + (hasTg ? "есть" : "нет") + " · initData:пусто · платформа:" + platform;
  document.body.appendChild(hint);
})();
const BOSS_WAIT = 10;               // секунд на точке: ждём напарника
const COOP = {open: false, id: 0, room: null, timer: 0, log: [], busy: false, coopSeen: false, rewarded: 0};

async function coopApi(path, body){
  const opts = {headers: {"X-Telegram-Init-Data": TG_INIT}};
  if (body !== undefined){
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let data = null;
  try {
    const res = await fetch(path, opts);
    try { data = await res.json(); } catch (e){ data = null; }
    if (!data) data = {error: "Сервер не ответил"};
    if (!res.ok && !data.error) data.error = "Ошибка " + res.status;
  } catch (e){
    data = {error: "Нет связи с сервером"};
  }
  return data;
}

function coopLog(text){
  COOP.log.unshift(text);
  COOP.log = COOP.log.slice(0, 7);
  const el = document.getElementById("clog");
  if (el) el.innerHTML = COOP.log.map(function(s){ return "<div>" + s + "</div>"; }).join("");
}

function coopTitle(room){
  if (room.status === "waiting") return "ЖДЁМ ВТОРОГО · " + room.ready_in + " с";
  if (room.status === "fight") return room.coop ? "БОЙ ВДВОЁМ" : "БОЙ · ОДИН";
  if (room.status === "dead") return "БОСС ПОВЕРЖЕН";
  if (room.status === "failed") return "ВСЕ ПАЛИ";
  return "КОМНАТА ЗАКРЫТА";
}

function coopApply(room){
  if (!room) return;
  const before = COOP.room ? COOP.room.status : null;
  COOP.room = room;
  const zone = document.getElementById("czone");
  const stat = document.getElementById("cstat");
  const name = document.getElementById("cname");
  if (zone) zone.textContent = (room.zone + 1) + "/10 · " + room.zone_name;
  if (stat) stat.textContent = coopTitle(room);
  if (name) name.textContent = "БОСС · " + String(room.zone_name).toUpperCase();
  const fill = document.getElementById("cbhp");
  if (fill) fill.style.width = Math.max(0, Math.min(100, room.hp / Math.max(1, room.max_hp) * 100)) + "%";
  const hpt = document.getElementById("cbhpt");
  if (hpt){
    hpt.textContent = "HP " + room.hp + " / " + room.max_hp +
      (room.status === "waiting"
        ? " · старт через " + room.ready_in + " с"
        : " · твой урон " + ((room.me && room.me.damage) || 0));
  }
  const team = document.getElementById("cteam");
  if (team){
    team.innerHTML = room.players.map(function(p){
      const cls = "cp" + (p.me ? " mine" : "") + (p.dead || p.left ? " out" : "");
      const width = Math.max(0, Math.round(p.hp / Math.max(1, p.max_hp) * 100));
      const label = p.me ? "ТЫ · " + p.name : p.name;
      return '<div class="' + cls + '"><b>' + label + "</b>" +
        '<div class="bar"><i style="width:' + width + '%"></i></div>' +
        "<span>HP " + p.hp + " / " + p.max_hp + " · " + p.damage +
        " урона · " + p.hits + " уд.</span></div>";
    }).join("");
  }
  const hitBtn = document.getElementById("chit");
  if (hitBtn){
    if (room.status === "waiting"){
      hitBtn.disabled = false;
      hitBtn.textContent = "⚔ НАЧАТЬ ОДИН";
    } else {
      const canHit = room.status === "fight" && room.me && !room.me.dead && room.cooldown <= 0;
      hitBtn.disabled = !canHit;
      hitBtn.textContent = room.status === "fight"
        ? (room.cooldown > 0 ? "⚔ " + room.cooldown.toFixed(1) + " с" : "⚔ УДАР")
        : "⚔ ЖДЁМ";
    }
  }
  if (before === "waiting" && room.status === "fight"){
    toast(room.coop ? "Напарник зашёл — бьём вдвоём!" : "Бой начался");
    if (!room.coop) coopLog("Напарника нет. Друг может подсесть в бой — пусть встанет в круг в этой же локации");
  }
  if (room.coop && !COOP.coopSeen){
    COOP.coopSeen = true;
    toast("Напарник в бою!");
    coopLog("<b>Напарник подсел</b> — боссу добавили HP");
  }
  if (!room.coop) COOP.coopSeen = false;
  // Награда начисляется один раз на комнату: число приходит с сервера,
  // а монеты добавляем в свой прогресс и сразу сохраняем.
  if (room.status === "dead" && room.reward && COOP.rewarded !== room.id){
    COOP.rewarded = room.id;
    const coins = Math.max(0, room.reward.coins | 0);
    P.coins += coins;
    stats.kills += Math.max(0, room.reward.kills | 0);
    coopLog("<b>Победа!</b> +" + coins + " монет и +" + (room.reward.yugi | 0) + " Югов");
    const bossLoot = room.reward.weapon ? weaponById(room.reward.weapon) : null;
    if (bossLoot){
      if (P.bag.indexOf(bossLoot.id) < 0) P.bag.push(bossLoot.id);
      coopLog("Дроп с босса: <b>" + bossLoot.name + "</b> · урон " + bossLoot.dmg);
      paintInv();
    }
    toast("Босс повержен: +" + coins + " монет" +
          (bossLoot ? " · " + bossLoot.name : ""));
    heroSave(true);
  }
  if (room.status === "dead" && before !== "dead") toast("Босс повержен!");
  if (room.status === "failed" && before !== "failed") toast("Вы пали. Возвращайся сильнее");
  if (room.status !== "waiting" && room.status !== "fight" && COOP.timer){
    clearInterval(COOP.timer);
    COOP.timer = 0;
  }
}

async function coopJoin(zone){
  const data = await coopApi("/api/dungeon/boss/join", {zone: zone});
  if (!data || !data.ok || !data.boss){
    if (data && data.error) toast(data.error);
    startBattle();                        // без Телеграма и без связи — локальный бой
    return;
  }
  COOP.open = true;
  COOP.id = data.boss.id;
  COOP.log = [];
  COOP.coopSeen = !!data.boss.coop;
  COOP.rewarded = 0;
  document.getElementById("coop").classList.add("on");
  coopLog("<b>Комната открыта</b> · " + data.boss.zone_name);
  if (data.boss.status === "waiting") coopLog("Ждём второго игрока на точке");
  coopApply(data.boss);
  if (!COOP.timer) COOP.timer = setInterval(coopPoll, 1500);
}

async function coopPoll(){
  if (!COOP.open || COOP.busy) return;
  COOP.busy = true;
  try {
    const data = await coopApi("/api/dungeon/boss/state");
    if (!data || !data.ok){
      if (data && data.error) coopLog(data.error);
      return;
    }
    if (!data.boss || data.boss.status === "none"){ await coopClose(true); return; }
    coopApply(data.boss);
  } finally {
    COOP.busy = false;
  }
}

async function coopHit(){
  const room = COOP.room;
  if (!COOP.open || !room) return;
  if (room.status === "waiting"){ await coopStart(); return; }
  if (room.status !== "fight" || !room.me || room.me.dead) return;
  const dmg = (P.weapon && P.weapon.dmg) || 12;
  const data = await coopApi("/api/dungeon/boss/hit", {damage: dmg});
  if (!data || !data.ok){
    if (data && data.error) coopLog(data.error);
    return;
  }
  const before = room.hp;
  coopApply(data.boss);
  if (data.boss.hit) coopLog("Удар на <b>" + data.boss.hit + "</b> · осталось " + data.boss.hp);
  else if (data.boss.cooldown > 0) coopLog("Кулдаун " + data.boss.cooldown.toFixed(1) + " с");
  if (data.boss.status === "dead" && before > 0) coopLog("<b>Босс повержен!</b>");
}

async function coopStart(){
  const data = await coopApi("/api/dungeon/boss/start", {});
  if (!data || !data.ok){
    if (data && data.error) coopLog(data.error);
    return;
  }
  coopLog("Начинаем вдвоём, если напарник успел");
  coopApply(data.boss);
}

async function coopClose(silent){
  if (!COOP.open) return;
  const room = COOP.room;
  COOP.open = false;
  document.getElementById("coop").classList.remove("on");
  if (COOP.timer){ clearInterval(COOP.timer); COOP.timer = 0; }
  COOP.room = null;
  COOP.id = 0;
  P.bossCd = 4;
  if (!silent && room && (room.status === "waiting" || room.status === "fight")){
    await coopApi("/api/dungeon/boss/leave", {});
  }
}

function coopUiTick(dt){
  const room = COOP.room;
  if (!COOP.open || !room) return;
  if (room.cooldown > 0){
    room.cooldown = Math.max(0, room.cooldown - dt);
    if (room.cooldown <= 0) coopApply(room);
    else {
      const btn = document.getElementById("chit");
      if (btn) btn.textContent = "⚔ " + room.cooldown.toFixed(1) + " с";
    }
  }
}

function bossEngage(bs){
  if (TG_INIT){ coopJoin(bs ? bs.zone : zoneIndex(P.y)); return; }
  toast("Нет данных Телеграма — бой локальный, без напарника");
  startBattle();                          // вне Телеграма — старый локальный бой
}

document.getElementById("chit").onclick = coopHit;
document.getElementById("cleave").onclick = function(){ coopClose(false); };


/* ---------- таблица лидеров ---------- */
async function openTop(){
  const box = document.getElementById("top");
  const list = document.getElementById("tplist");
  if (!box || !list) return;
  box.classList.add("on");
  list.textContent = "Загружаю…";
  const data = await coopApi("/api/dungeon/top");
  if (!data || !data.ok){
    list.textContent = (data && data.error) || "Не смог загрузить";
    return;
  }
  const rows = data.players || [];
  if (!rows.length){ list.textContent = "Пока никто не спускался"; return; }
  list.textContent = "";
  rows.forEach(function(row, index){
    const line = document.createElement("div");
    line.className = "tprow" + (row.id === data.me ? " mine" : "");
    const place = document.createElement("i");
    place.textContent = String(index + 1);
    const name = document.createElement("b");
    name.textContent = (row.id === data.me ? "ТЫ · " : "") + row.name;
    const stat = document.createElement("span");
    stat.textContent = "ур." + row.level + " · " + row.kills + " убийств · " +
      (row.armor ? "броня " + row.armor : "без брони");
    line.appendChild(place);
    line.appendChild(name);
    line.appendChild(stat);
    list.appendChild(line);
  });
}
document.getElementById("tpclose").onclick = function(){
  document.getElementById("top").classList.remove("on");
};

/* ---------- броня за Юги ---------- */
let HERO_ARMOR = null;

async function heroArmor(){
  if (!TG_INIT){ toast("Броня: открой через бота"); return; }
  if (!HERO_ARMOR){ toast("Броня уже максимальная"); return; }
  await heroSave(true);
  const data = await coopApi("/api/dungeon/armor", {});
  if (!data || !data.ok){
    toast((data && data.error) || "Не вышло купить броню");
    return;
  }
  heroApply(data.hero, false);
  sync();
  toast("Броня " + (P.armor || 0) + " · урон босса −" +
        Math.round((data.hero.armor_discount || 0) * 100) + "%");
}

/* ---------- хитбоксы домов ---------- */
function solidRects(){
  const rects = [];
  const here = zoneIndex(P.y);
  for (let z = Math.max(0, here - 1); z <= Math.min(ZONES.length - 1, here + 1); z++){
    const base = (ZONES.length - 1 - z) * ZONE_H;
    VILLAGE.forEach(function(v){
      if (v.kind !== "cottage") return;
      const vx = (z % 2) ? (WORLD.w - v.x) : v.x;
      // непроходимая часть — нижняя половина избы
      rects.push({
        x1: vx - v.w / 2 + 12,
        x2: vx + v.w / 2 - 12,
        y1: base + v.y - v.h * 0.45,
        y2: base + v.y - 6
      });
    });
  }
  return rects;
}
function blockedAt(x, y){
  const rects = solidRects();
  for (let i = 0; i < rects.length; i++){
    const r = rects[i];
    if (x > r.x1 && x < r.x2 && y > r.y1 && y < r.y2) return true;
  }
  return false;
}

/* ---------- чат подземелья ---------- */
// Общий чат на всех, кто в подземелье: тот же сокет, отдельный тип кадра.
const CHAT = {open: false, log: []};
const BUBBLES = {};

function chatRender(){
  const box = document.getElementById("chlog");
  if (!box) return;
  box.textContent = "";
  CHAT.log.forEach(function(m){
    const line = document.createElement("div");
    const who = document.createElement("b");
    who.textContent = m.name + ":";
    line.appendChild(who);
    line.appendChild(document.createTextNode(" " + m.text));
    box.appendChild(line);
  });
  box.scrollTop = box.scrollHeight;
}

function chatAdd(name, text){
  CHAT.log.push({
    name: String(name || "Игрок").slice(0, 16),
    text: String(text || "").slice(0, 80)
  });
  CHAT.log = CHAT.log.slice(-60);
  if (CHAT.open) chatRender();
}

function chatOpen(){
  CHAT.open = true;
  document.getElementById("chat").classList.add("on");
  chatRender();
  const field = document.getElementById("chtext");
  if (field && field.focus) field.focus();
}

function chatClose(){
  CHAT.open = false;
  document.getElementById("chat").classList.remove("on");
}

function chatSend(){
  const field = document.getElementById("chtext");
  const raw = String((field && field.value) || "");
  const text = raw.replace(/\s+/g, " ").trim().slice(0, 80);
  if (!text) return;
  if (!WS || WS.readyState !== 1){ toast("Чат: нет соединения с картой"); return; }
  if (field) field.value = "";
  try { WS.send(JSON.stringify({type: "chat", text: text})); } catch (e){}
}

document.getElementById("chclose").onclick = chatClose;
document.getElementById("chsend").onclick = chatSend;
document.getElementById("chtext").addEventListener("keydown", function(e){
  if (e.key === "Enter") chatSend();
});

/* ---------- редкость оружия ---------- */
// У мобов шанс дропа 5% и почти всегда низкий тир. Хорошее оружие —
// с боссов. Веса целочисленные, нормализуются суммой.
const MOB_DROP_CHANCE = 0.05;
const MOB_TIER_WEIGHTS = [46000, 26000, 14000, 8000, 4000, 1500, 400, 100, 30, 10];
const BOSS_TIER_WEIGHTS = [0, 0, 500, 3000, 12000, 26000, 30000, 20000, 6400, 10];

function rollWeapon(weights){
  const total = weights.reduce(function(a, b){ return a + b; }, 0);
  let point = Math.random() * total, tier = 0, acc = 0;
  for (let i = 0; i < weights.length; i++){
    acc += weights[i];
    if (point < acc){ tier = i; break; }
  }
  const kinds = ["sword", "bow", "staff"];
  return kinds[Math.floor(Math.random() * 3)] + "_" + tier + "_" +
    Math.floor(Math.random() * 5);
}

/* ---------- оффлайн-игроки в углу локации ---------- */
const OFFLINE = [];

function applyOffline(rows){
  OFFLINE.length = 0;
  (rows || []).forEach(function(row){
    if (row && row.zone != null) OFFLINE.push(row);
  });
}

function offlineSpot(spot, index){
  // стык 1-й и 2-й локаций, левый верхний угол стартовой: там не мешает HUD
  const junction = WORLD.h - ZONE_H;
  return {
    x: 56 + (index % 2) * 32,
    y: junction - 46 - Math.floor(index / 2) * 40
  };
}

function drawOffline(spot, index, t){
  const pos = offlineSpot(spot, index);
  if (Math.abs(pos.y - P.y) > ZONE_H * 1.6) return;
  const x = pos.x;
  const y = pos.y;
  const im = HEROES[spot.weapon === "bow" ? "elf_m" : "knight_m"];
  ctx.save();
  ctx.globalAlpha = 0.32;
  ctx.fillStyle = "#000";
  ctx.fillRect(x - 12, y + 6, 24, 5);
  ctx.globalAlpha = 0.55;
  if (im && im.complete && im.naturalWidth){
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(im, 0, 0, 16, 16, x - 24, y - 32, 48, 48);
  } else {
    person(x, y, "#6a6a7a");
  }
  ctx.restore();
  // табличка OFFLINE
  ctx.font = "7px 'Press Start 2P',monospace";
  ctx.textAlign = "center";
  ctx.fillStyle = "#12161dee";
  ctx.fillRect(x - 26, y + 10, 52, 12);
  ctx.fillStyle = "#8a8a9a";
  ctx.fillText("OFFLINE", x, y + 19);
  ctx.fillStyle = "#c9c4b0";
  ctx.fillText(String(spot.name || "Игрок").slice(0, 10), x, y - 38);
  // zZz
  const z = Math.sin(t * 1.6 + index) * 2;
  ctx.fillStyle = "#8fd8ff";
  ctx.globalAlpha = 0.75;
  ctx.fillText("z", x + 16, y - 44 + z);
  ctx.globalAlpha = 0.5;
  ctx.fillText("z", x + 24, y - 52 + z * 1.4);
  ctx.globalAlpha = 1;
}

function drawOfflineAll(t){
  let shown = 0;
  for (let i = 0; i < OFFLINE.length && shown < 12; i++){
    drawOffline(OFFLINE[i], shown, t);
    shown++;
  }
}

/* ---------- живые игроки на карте ---------- */
// Основной транспорт — WebSocket: 10 тактов в секунду, база не участвует.
// Если сокет не поднялся (прокси, старый WebView) — тихий откат на HTTP.
const REMOTE = {};
const FACE_ANGLE = [Math.PI / 2, Math.PI, 0, -Math.PI / 2];   // вниз, влево, вправо, вверх
let WS = null, wsTries = 0, wsOk = false, wsAuth = true, wsLastHttp = 0, presenceBusy = false;

function presencePayload(){
  return {
    x: Math.round(P.x), y: Math.round(P.y), zone: zoneIndex(P.y),
    facing: P.facing == null ? 0 : P.facing,
    anim: P.moving ? "run" : (P.atkCd > 0.25 ? "attack" : "idle"),
    hp: Math.round(P.hp), max_hp: Math.round(P.max),
    weapon: P.weapon ? P.weapon.kind : "sword"
  };
}

function applyPlayers(players){
  const now = performance.now();
  const alive = {};
  (players || []).forEach(function(p){
    const key = String(p.id);
    alive[key] = 1;
    let r = REMOTE[key];
    if (!r) r = REMOTE[key] = {x: p.x, y: p.y, tx: p.x, ty: p.y, seen: now};
    r.tx = p.x; r.ty = p.y;
    r.name = p.name; r.facing = p.facing; r.anim = p.anim;
    r.hp = p.hp; r.max_hp = p.max_hp; r.weapon = p.weapon; r.zone = p.zone;
    r.seen = now;
  });
  Object.keys(REMOTE).forEach(function(key){
    if (!alive[key] && now - (REMOTE[key].seen || 0) > 4000) delete REMOTE[key];
  });
}

function wsSend(){
  if (!WS || WS.readyState !== 1 || !wsOk) return;
  const payload = presencePayload();
  if (wsAuth) payload.init = TG_INIT;      // подпись нужна только в первом кадре
  try { WS.send(JSON.stringify(payload)); } catch (e){}
}

function wsStart(){
  if (!TG_INIT || WS) return;
  let sock;
  try {
    const proto = (location.protocol === "https:") ? "wss://" : "ws://";
    sock = new WebSocket(proto + location.host + "/ws/dungeon");
  } catch (e){ return; }
  WS = sock;
  sock.onopen = function(){ wsTries = 0; wsOk = true; wsAuth = true; wsSend(); };
  sock.onmessage = function(ev){
    let data = null;
    try { data = JSON.parse(ev.data); } catch (e){ return; }
    if (!data) return;
    if (data.type === "chat"){
      chatAdd(data.name, data.text);
      if (data.id) BUBBLES[data.id] = {text: String(data.text || "").slice(0, 40),
                                      until: performance.now() + 5000};
      if (!CHAT.open){
        toast(String(data.name || "Игрок").slice(0, 12) + ": " + String(data.text || "").slice(0, 40));
      }
      return;
    }
    if (data.error){ wsOk = false; try { sock.close(); } catch (e){} return; }
    wsAuth = false;
    applyPlayers(data.players);
    applyOffline(data.offline);
  };
  sock.onclose = function(){
    wsOk = false;
    if (WS === sock) WS = null;
    wsTries = Math.min(6, wsTries + 1);
    setTimeout(wsStart, 500 * wsTries);        // 0.5, 1, 1.5 ... 3 с
  };
  sock.onerror = function(){ try { sock.close(); } catch (e){} };
}

async function presenceTick(){
  if (!TG_INIT || presenceBusy || COOP.open || inBattle) return;
  presenceBusy = true;
  try {
    const data = await coopApi("/api/dungeon/presence", presencePayload());
    if (data && data.ok){
      applyPlayers(data.players);
      applyOffline(data.offline);
    }
  } catch (e){
  } finally {
    presenceBusy = false;
  }
}

function presenceLoop(){
  if (!TG_INIT || COOP.open || inBattle || document.hidden) return;
  if (WS && WS.readyState === 1 && wsOk){ wsSend(); return; }
  const now = performance.now();
  if (now - wsLastHttp > 600){ wsLastHttp = now; presenceTick(); }
}

function remoteTick(dt){
  const k = Math.min(1, dt * 9);
  Object.keys(REMOTE).forEach(function(key){
    const r = REMOTE[key];
    r.x += (r.tx - r.x) * k;
    r.y += (r.ty - r.y) * k;
  });
}

function drawRemote(r, t){
  const x = Math.max(24, Math.min(WORLD.w - 24, r.x));
  const y = Math.max(24, Math.min(WORLD.h - 24, r.y));
  const im = HEROES[r.weapon === "bow" ? "elf_m" : "knight_m"];
  ctx.save();
  ctx.globalAlpha = 0.25;
  ctx.fillStyle = "#000";
  ctx.fillRect(x - 13, y + 6, 26, 6);
  ctx.globalAlpha = 1;
  if (im && im.complete && im.naturalWidth){
    const moving = r.anim === "run" || r.anim === "attack";
    const frame = moving ? 4 + (Math.floor(t * 9 + x * 0.02) % 4) : Math.floor(t * 4) % 4;
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(im, frame * 16, 0, 16, 16, x - 26, y - 34, 52, 52);
  } else {
    person(x, y, "#c9a227");
  }
  ctx.restore();
  if (r.anim === "attack"){
    ctx.save();
    ctx.translate(x, y - 8);
    ctx.rotate(FACE_ANGLE[r.facing] || 0);
    ctx.globalCompositeOperation = "lighter";
    ctx.strokeStyle = "#ffd98a";
    ctx.lineWidth = 4;
    ctx.globalAlpha = 0.75;
    ctx.beginPath();
    ctx.arc(0, 0, 36, -0.7, 0.7);
    ctx.stroke();
    ctx.restore();
  }
  const bw = 46;
  ctx.fillStyle = "#000a";
  ctx.fillRect(x - bw / 2, y - 52, bw, 5);
  ctx.fillStyle = "#4ade80";
  ctx.fillRect(x - bw / 2, y - 52,
               bw * Math.max(0, Math.min(1, (r.hp || 0) / Math.max(1, r.max_hp || 1))), 5);
  ctx.fillStyle = "#ffe9b8";
  ctx.font = "7px 'Press Start 2P',monospace";
  ctx.textAlign = "center";
  ctx.fillText(String(r.name || "Игрок").slice(0, 12), x, y - 58);
  const bubble = BUBBLES[r.id];
  if (bubble && bubble.until > performance.now()){
    const label = String(bubble.text || "").slice(0, 26);
    const width = Math.min(170, ctx.measureText(label).width + 12);
    ctx.fillStyle = "#0d1016ee";
    ctx.fillRect(x - width / 2, y - 76, width, 14);
    ctx.fillStyle = "#ffe9b8";
    ctx.fillText(label, x, y - 66);
  }
}

if (TG_INIT){
  wsStart();
  setInterval(presenceLoop, 100);
}

/* ---------- прогресс героя: живёт в базе, а не во вкладке ---------- */
let heroLoaded = false, heroBusy = false, heroStamp = "", HERO_OFFER = null;

function heroSnapshot(){
  return {
    level: stats.lvl,
    exp: Math.round(stats.exp),
    coins: Math.max(0, Math.round(P.coins)),
    kills: stats.kills,
    weapon: P.weapon ? P.weapon.id : null,
    bag: (P.bag || []).slice(0, 200)
  };
}

function heroApply(hero, heal){
  if (!hero) return;
  const level = Math.max(1, hero.level | 0);
  stats.lvl = level;
  stats.exp = Math.max(0, hero.exp | 0);
  stats.kills = Math.max(0, hero.kills | 0);
  P.coins = Math.max(0, hero.coins | 0);
  const bag = (hero.bag || []).filter(function(id){ return !!weaponById(id); });
  if (bag.length) P.bag = bag;
  const weapon = hero.weapon ? weaponById(hero.weapon) : null;
  if (weapon) P.weapon = weapon;
  HERO_OFFER = hero.upgrade || null;
  HERO_ARMOR = hero.armor_offer || null;
  P.armor = hero.armor | 0;
  // проснуться там, где уснул
  if (hero.zone != null && hero.x != null && hero.y != null){
    P.x = Math.max(60, Math.min(WORLD.w - 60, hero.x));
    P.y = Math.max(60, Math.min(WORLD.h - 60, hero.y));
  }
  P.max = 120 + (level - 1) * 8;        // ровно как даёт повышение уровня
  if (heal !== false) P.hp = P.max;
}

async function heroLoad(){
  if (!TG_INIT || heroLoaded) return;
  const data = await coopApi("/api/dungeon/hero");
  if (data && data.ok && data.hero){
    heroApply(data.hero);
    heroLoaded = true;
    heroStamp = JSON.stringify(heroSnapshot());
    if (data.hero.level > 1 || data.hero.coins > 0){
      toast("Прогресс загружен: ур. " + data.hero.level + " · " + data.hero.coins + " монет");
    }
    fillMobs();                          // мобы по уровню, а не по первому
    sync();
  }
}

async function heroSave(force){
  if (!TG_INIT || !heroLoaded || heroBusy) return;
  const snapshot = heroSnapshot();
  const stamp = JSON.stringify(snapshot);
  if (!force && stamp === heroStamp) return;
  heroBusy = true;
  try {
    const data = await coopApi("/api/dungeon/hero", snapshot);
    if (data && data.ok) heroStamp = stamp;
  } catch (e){
  } finally {
    heroBusy = false;
  }
}

if (TG_INIT) setInterval(function(){ heroSave(false); }, 5000);

async function heroUpgrade(){
  const weapon = P.weapon;
  if (!weapon){ toast("Возьми оружие в руки"); return; }
  if (!TG_INIT){ toast("Улучшение: открой через бота"); return; }
  if (!HERO_OFFER){ toast("Дальше улучшать некуда"); return; }
  if (P.coins < HERO_OFFER.price){
    toast("Нужно " + HERO_OFFER.price + " монет, есть " + Math.round(P.coins));
    return;
  }
  // Сначала сохраняем монеты, чтобы сервер считал по актуальной сумме.
  await heroSave(true);
  const data = await coopApi("/api/dungeon/upgrade", {weapon: weapon.id});
  if (!data || !data.ok){
    toast((data && data.error) || "Не вышло улучшить");
    return;
  }
  heroApply(data.hero, false);
  sync();
  if (typeof paintInv === "function") paintInv();
  toast("Оружие улучшено: " + (P.weapon ? P.weapon.name : ""));
}

const ZONE_H = 1100;
const ZONES = [
  {n: "Опушка",         g: "#2a3d18", a: "#6a9a42", mob: 1.0,  sky: "#1a2410"},
  {n: "Дубовая роща",   g: "#243615", a: "#5c8a38", mob: 1.3,  sky: "#16200e"},
  {n: "Болото",         g: "#1e2e1a", a: "#4a7040", mob: 1.7,  sky: "#121a12"},
  {n: "Каменный перевал", g: "#26262e", a: "#5e5e6e", mob: 2.2, sky: "#15151c"},
  {n: "Пепельный лес",  g: "#2a211b", a: "#6a5340", mob: 2.8,  sky: "#1a1410"},
  {n: "Костяные поля",  g: "#2d2c26", a: "#6e6c5c", mob: 3.4,  sky: "#1b1a16"},
  {n: "Багровые шахты", g: "#331818", a: "#7a3a3a", mob: 4.1,  sky: "#1e0e0e"},
  {n: "Ледяные залы",   g: "#1b2733", a: "#4a6a8a", mob: 4.9,  sky: "#101820"},
  {n: "Тёмный алтарь",  g: "#1f1726", a: "#4e3a62", mob: 5.8,  sky: "#150f1c"},
  {n: "Бездна",         g: "#110a0e", a: "#3a1a24", mob: 7.0,  sky: "#0a0508"}
];
const WORLD = {
  w: Math.max(480, window.innerWidth || 480),
  h: ZONE_H * ZONES.length
};
function zoneIndex(y){
  // низ карты = локация 1, верх = последняя
  const raw = Math.floor(y / ZONE_H);
  return Math.max(0, Math.min(ZONES.length - 1, ZONES.length - 1 - raw));
}
function zoneAt(y){ return ZONES[zoneIndex(y)]; }
function zoneReq(y){ return 1 + zoneIndex(y) * 25; }   // 1, 26, 51, 76, ...
const DECOR = (function(){
  const list = [];
  // лес по краям
  for (let i = 0; i < 90; i++){
    const side = Math.random() < 0.5;
    const x = side ? 20 + Math.random() * 120 : WORLD.w - 20 - Math.random() * 120;
    list.push({k: "tree", x: x, y: 40 + Math.random() * (WORLD.h - 80),
               s: 0.8 + Math.random() * 0.6});
  }
  // кусты и камни внутри
  for (let i = 0; i < 46; i++){
    const t = Math.random();
    list.push({k: t < 0.55 ? "bush" : t < 0.85 ? "rock" : "grass",
               x: 180 + Math.random() * (WORLD.w - 360),
               y: 60 + Math.random() * (WORLD.h - 120),
               s: 0.7 + Math.random() * 0.7});
  }
  list.sort(function(a, b){ return a.y - b.y; });
  return list;
})();
const VILLAGE = [
  {kind: "cottage", x: 150, y: 330, w: 140, h: 140},
  {kind: "cottage", x: 330, y: 290, w: 140, h: 140},
  {kind: "cottage", x: 140, y: 760, w: 140, h: 140},
  {kind: "cottage", x: 340, y: 850, w: 140, h: 140},
  {kind: "lamp",    x: 240, y: 520, w: 40, h: 80},
  {kind: "lamp",    x: 240, y: 960, w: 40, h: 80},
  {kind: "bench",   x: 300, y: 620, w: 70, h: 35},
  {kind: "bench",   x: 180, y: 1060, w: 70, h: 35},
  {kind: "bed",     x: 100, y: 500, w: 70, h: 35},
  {kind: "bed",     x: 390, y: 700, w: 70, h: 35}
];
const PATH = (function(){
  const pts = [];
  for (let i = 0; i <= 40; i++){
    const t = i / 40;
    pts.push({
      x: WORLD.w / 2 + Math.sin(t * 5) * 90,
      y: WORLD.h - 60 - t * (WORLD.h - 220)
    });
  }
  return pts;
})();
let P = {x: WORLD.w / 2, y: WORLD.h - 260, hp: 120, max: 120, coins: 0,
         weapon: null, bag: [], atkCd: 0, shCd: 0, abCd: 0, dashCd: 0, dashT: 0,
         shield: 0, dir: 0};
const WEAPONS = (function(){
  var kinds = [
    {k: "sword", n: "Меч", range: 82, cls: "мечник"},
    {k: "bow", n: "Лук", range: 150, cls: "лучник"},
    {k: "staff", n: "Посох", range: 125, cls: "маг"}
  ];
  var tierName = ["Ржавый", "Простой", "Крепкий", "Стальной", "Клёпаный",
                  "Закалённый", "Рунный", "Драконий", "Небесный", "Бездонный"];
  var list = [];
  kinds.forEach(function(kd){
    for (var t = 0; t < 10; t++){
      for (var v = 0; v < 5; v++){
        var power = (1 + t * 0.9) * (1 + v * 0.12);
        list.push({
          id: kd.k + "_" + t + "_" + v,
          name: tierName[t] + " " + kd.n + " " + (v + 1),
          kind: kd.k,
          cls: kd.cls,
          range: kd.range + t * 3,
          dmg: Math.round((kd.k === "bow" ? 8 : kd.k === "staff" ? 10 : 12) * power),
          spd: +(1.0 - t * 0.015).toFixed(3),
          tier: t
        });
      }
    }
  });
  return list;
})();
function weaponById(id){ return WEAPONS.filter(function(w){ return w.id === id; })[0]; }
let cam = {x: 0, y: 0};
let mobs = [], hits = [], drop = [];
let bosses = [];
for (let i = 0; i < ZONES.length; i++){
  const zid = ZONES.length - 1 - i;
  bosses.push({x: WORLD.w / 2 - 180, y: i * ZONE_H + 300, r: 60, t: 0, zone: zid, idx: 0});
  bosses.push({x: WORLD.w / 2 + 180, y: i * ZONE_H + 780, r: 60, t: 0, zone: zid, idx: 1});
}
let boss = bosses[0];
let stats = {kills: 0, lvl: 1, exp: 0};
let inBattle = false;

function rnd(a, b){ return a + Math.random() * (b - a); }
function toast(t){
  const el = document.getElementById("toast");
  el.textContent = t; el.className = "on";
  clearTimeout(el._t); el._t = setTimeout(() => el.className = "", 2500);
}
/* ---------- мир ---------- */
// Мобы живут во всех локациях, а не только там, где сейчас игрок: иначе
// соседние уровни пустые и кажется, что мир вымер.
const MOB_PER_ZONE = 6;      // в локации игрока
const MOB_PER_NEAR = 3;      // в соседних
const MOB_CAP = 44;          // больше держать нет смысла
const MOB_KEEP_ZONES = 2;    // дальше этого от игрока мобов выкидываем
let spawnTimer = 0;

function zoneBand(zi){
  const base = (ZONES.length - 1 - zi) * ZONE_H;
  return {from: base + 90, to: base + ZONE_H - 90};
}
function mobsInZone(zi){
  let n = 0;
  for (let i = 0; i < mobs.length; i++){
    if (zoneIndex(mobs[i].y) === zi) n++;
  }
  return n;
}
function spawnMobs(n){
  mobs = [];
  fillMobs();
}
function fillMobs(){
  const here = zoneIndex(P.y);
  for (let d = -1; d <= 1; d++){
    const zi = here + d;
    if (zi < 0 || zi >= ZONES.length) continue;
    const quota = d === 0 ? MOB_PER_ZONE : MOB_PER_NEAR;
    for (let i = mobsInZone(zi); i < quota; i++) spawnOne(zi);
  }
}
const MOB_TYPES = [
  {n: "Слизь",   hp: 30,  sp: 20, dmg: 6,  c: "#6fa86f", sz: 0.85, tile: [0, 9]},
  {n: "Летучая", hp: 22,  sp: 48, dmg: 5,  c: "#8a7a5a", sz: 0.7,  tile: [4, 9]},
  {n: "Скелет",  hp: 70,  sp: 26, dmg: 11, c: "#c9c4b0", sz: 1.05, tile: [1, 9]},
  {n: "Огр",     hp: 120,  sp: 36, dmg: 14, c: "#5a8a4a", sz: 0.95, tile: [2, 9]},
  {n: "Паук",    hp: 90,  sp: 52, dmg: 13, c: "#6a4a7a", sz: 0.85, tile: [0, 8]},
  {n: "Тролль",  hp: 300, sp: 17, dmg: 24, c: "#3f6a4a", sz: 1.45, tile: [0, 7]},
  {n: "Демон",   hp: 520, sp: 30, dmg: 38, c: "#8a2a2a", sz: 1.3,  tile: [3, 7]},
  {n: "Призрак", hp: 430, sp: 24, dmg: 32, c: "#4a5a9a", sz: 1.15, tile: [4, 7]},
  {n: "Крыса",    hp: 26,  sp: 58, dmg: 5,  c: "#8a7a5a", sz: 0.7,  tile: [3, 9]},
  {n: "Зомби",    hp: 110, sp: 22, dmg: 15, c: "#5a7a4a", sz: 1.0,  tile: [2, 8]},
  {n: "Гуль",     hp: 160, sp: 34, dmg: 22, c: "#7a6a5a", sz: 1.05, tile: [1, 8]},
  {n: "Рыцарь",   hp: 240, sp: 26, dmg: 30, c: "#8a8a9a", sz: 1.1,  tile: [3, 8]},
  {n: "Оборотень",hp: 380, sp: 46, dmg: 40, c: "#6a5a4a", sz: 1.15, tile: [4, 8]},
  {n: "Вампир",   hp: 600, sp: 38, dmg: 55, c: "#7a1a2a", sz: 1.15, tile: [2, 7]},
  {n: "Голем",    hp: 900, sp: 16, dmg: 70, c: "#5a5a4a", sz: 1.5,  tile: [0, 9]},
  {n: "Дракон",   hp: 1400, sp: 30, dmg: 95, c: "#a04a1a", sz: 1.45, tile: [1, 9]}
];
function spawnOne(zi){
  if (mobs.length >= MOB_CAP) return;
  zi = (zi == null) ? zoneIndex(P.y) : Math.max(0, Math.min(ZONES.length - 1, zi));
  const band = zoneBand(zi);
  const x = rnd(90, Math.max(140, WORLD.w - 90));
  const y = band.from + Math.random() * (band.to - band.from);
  const pool = Math.min(MOB_TYPES.length, 2 + zi * 2 + Math.floor(stats.lvl / 6));
  const type = MOB_TYPES[Math.floor(Math.random() * Math.max(2, pool))];
  // сила зависит от локации, в которой моб стоит, а не от игрока:
  // в глубину слабый игрок просто не пройдёт
  const zoneMul = Math.pow(2.4, zi);
  const grow = (1 + (stats.lvl - 1) * 0.12) * zoneMul;
  mobs.push({x: x, y: y, hp: Math.round(type.hp * grow), max: Math.round(type.hp * grow),
             sp: type.sp, dmg: type.dmg * (1 + zi * 0.9), c: type.c, sz: type.sz, nm: type.n,
             tile: type.tile, t: rnd(0, 6), hit: 0, zone: zi});
}
function reset(){
  P.x = WORLD.w / 2; P.y = WORLD.h - 260;
  P.max = 120; P.hp = 120; P.atkCd = 0; P.shCd = 0; P.abCd = 0; P.shield = 0; P.dashCd = 0; P.dashT = 0;
  if (!P.weapon) P.weapon = WEAPONS[2];
  if (!P.bag || !P.bag.length) P.bag = [WEAPONS[2].id];
  spawnMobs(18);
}
/* ---------- ввод ---------- */
const keys = {};
addEventListener("keydown", e => { keys[e.key.toLowerCase()] = true; });
addEventListener("keyup", e => { keys[e.key.toLowerCase()] = false; });
let joyV = {x: 0, y: 0}, joyId = null;
const joyEl = document.getElementById("joy"), knob = document.getElementById("knob");
function joyStart(e){
  joyId = e.pointerId; joyMove(e);
}
function joyMove(e){
  if (e.pointerId !== joyId) return;
  const r = joyEl.getBoundingClientRect();
  let dx = e.clientX - (r.left + r.width / 2);
  let dy = e.clientY - (r.top + r.height / 2);
  const len = Math.hypot(dx, dy) || 1, max = r.width / 2 - 12;
  const k = Math.min(1, max / len);
  dx *= k; dy *= k;
  knob.style.transform = "translate(" + dx + "px," + dy + "px)";
  joyV = {x: dx / max, y: dy / max};
}
function joyEnd(e){
  if (e.pointerId !== joyId) return;
  joyId = null; joyV = {x: 0, y: 0}; knob.style.transform = "";
}
joyEl.addEventListener("pointerdown", joyStart);
addEventListener("pointermove", joyMove);
addEventListener("pointerup", joyEnd);
addEventListener("pointercancel", joyEnd);

/* ---------- бой на карте ---------- */
function attack(){
  if (P.atkCd > 0 || inBattle) return;
  const w = P.weapon;
  if (!w) return;
  const range = Number(w.range) || 80;
  const dmg = Number(w.dmg) || 12;
  P.atkCd = w.kind === "bow" ? 0.7 * w.spd : 0.45 * w.spd;
  FX.swingAt(P.dir, w.kind);
  const fxCol = w.kind === "bow" ? "#8bd65a" : w.kind === "staff" ? "#8fd8ff" : "#ffd98a";
  let hitAny = false;
  mobs.forEach(m => {
    const d = Math.hypot(m.x - P.x, m.y - P.y);
    if (d < range){
      m.hp -= dmg; m.hit = 0.25; hitAny = true;
      hits.push({x: m.x, y: m.y - 26, t: 0.9, v: Math.round(dmg), c: "#ffd98a"});
      FX.burst(m.x, m.y - 14, 7, fxCol, 170, 13);
      if (m.hp <= 0) killMob(m);
    }
  });
  if (!hitAny) hits.push({x: P.x, y: P.y - 34, t: 0.5, v: "", c: "#8b93a7"});
}
function killMob(m){
  const i = mobs.indexOf(m);
  if (i >= 0) mobs.splice(i, 1);
  FX.burst(m.x, m.y - 10, 16, m.c || "#ffd98a", 210, 18);
  FX.glowAt(m.x, m.y - 10, 120, "#ffd98a", 0.6);
  const zr = zoneReq(m.y);
  const tooStrong = stats.lvl < zr;
  const power = Math.max(1, Math.round(m.max / 30));
  if (tooStrong){
    P.coins += 1;
    toast("Слабо для этой локации: нужен ур. " + zr + " — опыта нет");
  } else {
    P.coins += 3 + Math.floor(Math.random() * 5);
    stats.exp += 12 + power * 4;
  }
  stats.kills += 1;
  if (stats.exp >= stats.lvl * 100){ stats.lvl += 1; stats.exp = 0; P.max += 8; P.hp = P.max;
    toast("Уровень " + stats.lvl + "! HP вырос"); heroSave(true); }
  if (Math.random() < MOB_DROP_CHANCE){
    const loot = weaponById(rollWeapon(MOB_TIER_WEIGHTS)) || WEAPONS[0];
    const isNew = P.bag.indexOf(loot.id) < 0;
    if (isNew) P.bag.push(loot.id);
    drop.push({x: m.x, y: m.y, kind: "weapon", t: 8, name: loot.name});
    toast((isNew ? "НОВОЕ! " : "") + loot.name +
          " · " + loot.cls + " · урон " + loot.dmg + " · дальн. " + loot.range +
          (isNew ? " — загляни в сумку" : ""));
  }
  if (mobs.length < 10) fillMobs();
  sync();
}
function shieldUp(){
  if (P.dashCd > 0 || inBattle) return;
  P.dashCd = 2.2; P.dashT = 0.22; P.shield = 0.22;
  const a = (typeof P.dir === "number") ? P.dir : 0;
  P.dashVX = Math.cos(a) * 700;
  P.dashVY = Math.sin(a) * 700;
}
function ability(){
  if (P.abCd > 0) return;
  const dmgA = Number(P.weapon && P.weapon.dmg) || 12;
  P.abCd = 8;
  const kind = P.weapon ? P.weapon.kind : "sword";
  if (kind === "staff"){
    mobs.slice().forEach(m => {
      if (Math.hypot(m.x - P.x, m.y - P.y) < 210){ m.hp -= dmgA * 1.6; m.hit = .3;
        hits.push({x: m.x, y: m.y - 26, t: .9, v: Math.round(dmgA * 1.6), c: "#9fd6ff"});
        if (m.hp <= 0) killMob(m); }
    });
  } else if (kind === "bow"){
    mobs.slice().forEach(m => {
      if (Math.hypot(m.x - P.x, m.y - P.y) < 260){ m.hp -= dmgA * 0.8; m.hit = .3;
        hits.push({x: m.x, y: m.y - 26, t: .9, v: Math.round(dmgA * 0.8), c: "#8bd65a"});
        if (m.hp <= 0) killMob(m); }
    });
  } else {
    mobs.slice().forEach(m => {
      if (Math.hypot(m.x - P.x, m.y - P.y) < 110){ m.hp -= dmgA * 2.2; m.hit = .3;
        hits.push({x: m.x, y: m.y - 26, t: .9, v: Math.round(dmgA * 2.2), c: "#e24646"});
        if (m.hp <= 0) killMob(m); }
    });
  }
  const abCol = kind === "staff" ? "#8fd8ff" : kind === "bow" ? "#8bd65a" : "#ff5a5a";
  FX.glowAt(P.x, P.y - 8, 360, abCol, 0.85);
  FX.burst(P.x, P.y - 8, 24, abCol, 280, 16);
  FX.shake(4);
  toast("Способность!");
}
document.getElementById("attack").onclick = attack;
document.getElementById("shield").onclick = shieldUp;
document.getElementById("ability").onclick = ability;

/* ---------- босс ---------- */
let B = null;
function startBattle(){
  inBattle = true;
  const zb = boss ? ZONES[boss.zone] : ZONES[0];
  const power = zb.mob;
  B = {hp: Math.round(600 * power), max: Math.round(600 * power),
       name: "Босс · " + zb.n, atk: 16 * power, cd: 0, pcd: 0};
  document.getElementById("battle").classList.add("on");
  document.getElementById("ename").textContent = B.name;
  drawFighters();
  syncBattle();
}
function endBattle(win){
  inBattle = false; B = null;
  document.getElementById("battle").classList.remove("on");
  if (win){
    P.coins += 120;
    FX.burst(boss.x, boss.y, 40, "#ffd98a", 320, 22);
    FX.shake(9);
    const loot = weaponById(rollWeapon(BOSS_TIER_WEIGHTS));
    if (loot && P.bag.indexOf(loot.id) < 0){ P.bag.push(loot.id); paintInv(); }
    toast(loot ? ("Босс повержен! +120 монет · " + loot.name) : "Босс повержен! +120 монет");
  } else {
    toast("Ты проиграл. Возвращайся сильнее");
    P.hp = P.max;
  }
  boss.t = 0;
  P.bossCd = 6;
  sync();
}
function syncBattle(){
  if (!B) return;
  document.getElementById("php").style.width = Math.max(0, P.hp / P.max * 100) + "%";
  document.getElementById("ehp").style.width = Math.max(0, B.hp / B.max * 100) + "%";
}
document.getElementById("battack").onclick = () => {
  if (!B || B.pcd > 0) return;
  B.hp -= (Number(P.weapon && P.weapon.dmg) || 12) * 1.4; B.pcd = 0.55;
  syncBattle();
  if (B.hp <= 0) endBattle(true);
};
document.getElementById("bshield").onclick = () => { if (B) P.shield = 1.6; };
document.getElementById("bability").onclick = () => {
  if (!B || P.abCd > 0) return;
  P.abCd = 7; B.hp -= (Number(P.weapon && P.weapon.dmg) || 12) * 2.6; syncBattle();
  if (B.hp <= 0) endBattle(true);
};
document.getElementById("bflee").onclick = () => endBattle(false);

/* ---------- отрисовка ---------- */
function drawFighters(){
  [["pcv", "#4a9eff"], ["ecv", "#e24646"]].forEach(([id, color]) => {
    const c = document.getElementById(id).getContext("2d");
    c.clearRect(0, 0, 200, 220);
    c.fillStyle = color;
    c.beginPath(); c.arc(100, 70, 34, 0, 7); c.fill();
    c.fillStyle = "#0b0e14";
    c.fillRect(60, 108, 80, 90);
    c.fillStyle = color;
    c.fillRect(66, 112, 68, 82);
  });
}
const LPC = {};
const HEAD = new Image();
HEAD.src = "/static/lpc_head.png";
const TORSO = new Image();
TORSO.src = "/static/lpc_torso.png";
const KENNEY = new Image();
KENNEY.src = "/static/kenney.png";
const TOWN = new Image();
TOWN.src = "/static/town.png";
const FARM = {};
["cottage-blue", "lamppost", "bench", "flower-bed", "baker"].forEach(function(k){
  const im = new Image();
  im.src = "/static/farm/" + k + ".png";
  FARM[k] = im;
});
function drawFarm(key, x, y, w, h){
  const im = FARM[key];
  if (!im || !im.complete || !im.naturalWidth) return false;
  ctx.save();
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(im, x - w / 2, y - h, w, h);
  ctx.restore();
  return true;
}
// блок тайлов из атласа деревни: (колонка, ряд, сколько тайлов)
function drawBlock(col, row, tiles, x, y, size){
  if (!TOWN.complete || !TOWN.naturalWidth) return false;
  ctx.save();
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(TOWN, col * 16, row * 16, tiles * 16, tiles * 16,
                x - size / 2, y - size + 8, size, size);
  ctx.restore();
  return true;
}
function drawTile(t, x, y, size, bob){
  if (!t || !KENNEY.complete || !KENNEY.naturalWidth) return false;
  ctx.save();
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(KENNEY, t[0] * 16, t[1] * 16, 16, 16,
                x - size / 2, y - size + 6 + (bob || 0), size, size);
  ctx.restore();
  return true;
}
["walk", "slash", "run"].forEach(function(k){
  const im = new Image();
  im.src = "/static/lpc_" + k + ".png";
  LPC[k] = im;
});
const LPC_FRAMES = {walk: 9, slash: 6, run: 8};
function faceRow(face){                    // LPC: 0 вверх, 1 влево, 2 вниз, 3 вправо
  return face === 0 ? 2 : face === 1 ? 1 : face === 2 ? 3 : 0;
}
let animT = 0;
const HEROES = {};
["knight_m", "elf_m"].forEach(function(k){
  const im = new Image();
  im.src = "/static/hero_" + k + ".png";
  HEROES[k] = im;
});
function drawHero(x, y, attacking){
  const key = (P.weapon && P.weapon.kind === "bow") ? "elf_m" : "knight_m";
  const im = HEROES[key];
  const bob = attacking ? -2 : (P.moving ? Math.sin(animT * 10) * 1.2 : 0);
  const lunge = attacking ? 4 : 0;
  ctx.globalAlpha = 0.25;
  ctx.fillStyle = "#000"; ctx.fillRect(x - 13, y + 6, 26, 6);
  ctx.globalAlpha = 1;
  if (!im || !im.complete || !im.naturalWidth){
    if (!drawTile([1, 7], x, y, 42, 0)) person(x, y, "#4a9eff");
    return;
  }
  let frame;
  if (attacking) frame = 4 + (Math.floor(animT * 16) % 4);        // run-кадры = замах
  else if (P.moving) frame = 4 + (Math.floor(animT * 9) % 4);     // бег
  else frame = Math.floor(animT * 4) % 4;                          // покой
  ctx.save();
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(im, frame * 16, 0, 16, 16,
                x - 26 + lunge, y - 34 + bob, 52, 52);
  ctx.restore();
}
function person(x, y, color, label, alpha, walk){
  ctx.globalAlpha = alpha == null ? 1 : alpha;
  const bob = walk ? Math.sin(Date.now() / 140) * 1.5 : 0;
  ctx.fillStyle = "#00000066";
  ctx.fillRect(x - 12, y + 16, 24, 5);
  ctx.fillStyle = "#241a2e";
  ctx.fillRect(x - 7, y + 8, 6, 10);
  ctx.fillRect(x + 1, y + 8, 6, 10);
  ctx.fillStyle = color;
  ctx.fillRect(x - 9, y - 6 + bob, 18, 16);
  ctx.fillStyle = "#00000033";
  ctx.fillRect(x - 9, y + 4 + bob, 18, 6);
  ctx.fillStyle = "#e8c99a";
  ctx.fillRect(x - 8, y - 20 + bob, 16, 14);
  ctx.fillStyle = "#120e18";
  ctx.fillRect(x - 5, y - 15 + bob, 3, 4);
  ctx.fillRect(x + 2, y - 15 + bob, 3, 4);
  ctx.fillStyle = color;
  ctx.fillRect(x - 9, y - 24 + bob, 18, 6);
  if (label){
    ctx.fillStyle = "#8a7a9a"; ctx.font = "7px 'Press Start 2P',monospace";
    ctx.textAlign = "center"; ctx.fillText(label, x, y + 32);
  }
  ctx.globalAlpha = 1;
}
function loop(now){
  requestAnimationFrame(loop);
  const dt = Math.min(0.05, (now - (loop.last || now)) / 1000);
  loop.last = now;
  FX.tick(dt);
  FX.step(dt);
  coopUiTick(dt);
  remoteTick(dt);
  if (!P.weapon || inBattle || COOP.open){ render(dt); return; }

  let vx = joyV.x, vy = joyV.y;
  if (keys["w"] || keys["ц"] || keys["arrowup"]) vy = -1;
  if (keys["s"] || keys["ы"] || keys["arrowdown"]) vy = 1;
  if (keys["a"] || keys["ф"] || keys["arrowleft"]) vx = -1;
  if (keys["d"] || keys["в"] || keys["arrowright"]) vx = 1;
  const len = Math.hypot(vx, vy);
  if (len > 1){ vx /= len; vy /= len; }
  const speed = 210;
  const nextX = Math.max(30, Math.min(WORLD.w - 30, P.x + vx * speed * dt));
  const nextY = Math.max(30, Math.min(WORLD.h - 30, P.y + vy * speed * dt));
  // Дома не пропускают: если стоим в стене (застряли), даём выйти.
  const stuck = blockedAt(P.x, P.y);
  if (stuck || !blockedAt(nextX, P.y)) P.x = nextX;
  if (stuck || !blockedAt(P.x, nextY)) P.y = nextY;
  P.dashCd = Math.max(0, P.dashCd - dt);
  if (P.dashT > 0){
    P.dashT -= dt;
    const dashX = Math.max(30, Math.min(WORLD.w - 30, P.x + (P.dashVX || 0) * dt));
    const dashY = Math.max(30, Math.min(WORLD.h - 30, P.y + (P.dashVY || 0) * dt));
    if (!blockedAt(dashX, P.y)) P.x = dashX;
    if (!blockedAt(P.x, dashY)) P.y = dashY;
  }
  P.moving = len > 0.05;
  if (P.moving){
    P.dustT = (P.dustT || 0) - dt;
    if (P.dustT <= 0){ P.dustT = 0.07; FX.dust(P.x + rnd(-4, 4), P.y + 10, 1); }
  }
  if (len > 0.05){
    P.dir = Math.atan2(vy, vx);
    P.facing = Math.abs(vx) > Math.abs(vy) ? (vx < 0 ? 1 : 2) : (vy < 0 ? 3 : 0);
  }

  P.atkCd = Math.max(0, P.atkCd - dt);
  P.shCd = Math.max(0, P.shCd - dt);
  P.abCd = Math.max(0, P.abCd - dt);
  P.shield = Math.max(0, P.shield - dt);

  mobs.forEach(m => {
    m.t -= dt;
    if (m.t <= 0){ m.t = rnd(1.5, 4); m.vx = rnd(-1, 1); m.vy = rnd(-1, 1); }
    const dm = Math.hypot(P.x - m.x, P.y - m.y);
    const strong = stats.lvl < zoneReq(m.y) ? 2.5 : 1;
    if (dm < 260){
      m.x += (P.x - m.x) / dm * m.sp * dt;
      m.y += (P.y - m.y) / dm * m.sp * dt;
      if (dm < 34 && P.shield <= 0){
        P.hp -= (m.dmg || 6) * dt * 1.6 * (stats.lvl < zoneReq(m.y) ? 2.5 : 1);
        FX.hurt();
        FX.burst(m.x, m.y - 12, 4, "#ff3b52", 90, 9);
        if (P.hp <= 0){
          // База — это старт подземелья (Опушка), а не середина карты.
          P.hp = P.max;
          P.x = WORLD.w / 2;
          P.y = WORLD.h - 260;
          FX.shake(6);
          toast("Тебя оттащило на базу · ЛОК. 1/10");
        }
      }
    } else {
      m.x += (m.vx || 0) * m.sp * dt; m.y += (m.vy || 0) * m.sp * dt;
      m.x = Math.max(60, Math.min(WORLD.w - 60, m.x));
      m.y = Math.max(60, Math.min(WORLD.h - 60, m.y));
    }
    m.hit = Math.max(0, m.hit - dt);
  });
  animT += dt;
  // население мира: своя локация и соседние держим заполненными,
  // а тех, кто остался далеко позади, убираем
  spawnTimer -= dt;
  if (spawnTimer <= 0){
    spawnTimer = 0.25;
    const here = zoneIndex(P.y);
    let far = 0;
    for (let i = 0; i < mobs.length; i++){
      if (Math.abs(zoneIndex(mobs[i].y) - here) > MOB_KEEP_ZONES) far++;
    }
    if (far){
      mobs = mobs.filter(function(m){
        return Math.abs(zoneIndex(m.y) - here) <= MOB_KEEP_ZONES;
      });
    }
    for (let d = -1; d <= 1; d++){
      const zi = here + d;
      if (zi < 0 || zi >= ZONES.length) continue;
      const quota = d === 0 ? MOB_PER_ZONE : MOB_PER_NEAR;
      if (mobsInZone(zi) < quota){ spawnOne(zi); break; }
    }
  }
  hits = hits.filter(h => { h.t -= dt; h.y -= 26 * dt; return h.t > 0; });
  drop = drop.filter(d => {
    d.t -= dt;
    if (Math.hypot(d.x - P.x, d.y - P.y) < 34){
      const loot = WEAPONS.filter(function(w){ return w.name === d.name; })[0];
      if (loot){
        if (P.bag.indexOf(loot.id) < 0) P.bag.push(loot.id);
        toast("Подобрал: " + loot.name + " · урон " + loot.dmg);
        refreshInv();
      }
      return false;
    }
    return d.t > 0;
  });

  // ожидание босса: 5 секунд в круге — и бой
  P.bossCd = Math.max(0, (P.bossCd || 0) - dt);
  if (!inBattle && P.bossCd <= 0){
    bosses.forEach(function(bs){
      const inside = Math.hypot(bs.x - P.x, bs.y - P.y) < bs.r;
      if (!inside){
        bs.t = Math.max(0, bs.t - dt * 2);
        return;
      }
      const req = zoneReq(bs.y);
      if (stats.lvl < req){
        bs.t = 0;
        if (!bs.warned){ bs.warned = true; toast("Босс: нужен ур. " + req); }
        return;
      }
      bs.warned = false;
      bs.t += dt;
      if (bs.t >= BOSS_WAIT){
        bs.t = 0;
        boss = bs;
        FX.burst(bs.x, bs.y, 26, "#ff7a3c", 220, 20);
        FX.shake(7);
        bossEngage(bs);
        return;
      }
      if (Math.random() < dt * 8) FX.emit(bs.x + rnd(-bs.r, bs.r), bs.y + rnd(-bs.r, bs.r) * 0.4,
        {vx: 0, vy: -26, life: 0.7, size: 8, col: "#ff7a3c", drag: 1});
    });
  }

  render(dt);
  document.getElementById("hpfill").style.width = Math.max(0, P.hp / P.max * 100) + "%";
  document.getElementById("hptxt").textContent =
    "HP " + Math.round(P.hp) + " / " + P.max + "  ·  ур. " + stats.lvl;
  document.getElementById("coins").textContent = P.coins;
  if (P.weapon){
    const el = document.getElementById("wname");
    if (el) el.textContent = P.weapon.name;
    const e2 = document.getElementById("wcls");
    if (e2) e2.textContent = P.weapon.cls;
    const e3 = document.getElementById("wdmg");
    if (e3) e3.textContent = P.weapon.dmg;
    const e4 = document.getElementById("wrange");
    if (e4) e4.textContent = P.weapon.range;
    const e5 = document.getElementById("wspd");
    if (e5) e5.textContent = P.weapon.spd || 1;
  }
  const zi = zoneIndex(P.y);
  const zel = document.getElementById("zone");
  if (zel) zel.textContent = "ЛОК. " + (zi + 1) + "/10 · " + ZONES[zi].n + " · ур." + (1 + zi * 25);
  ["attack", "shield", "ability"].forEach(k => {
    const el = document.getElementById(k);
    const cd = k === "attack" ? P.atkCd : k === "shield" ? P.dashCd : P.abCd;
    el.classList.toggle("cool", cd > 0.05);
    const s = document.getElementById("cd" + k[0].toUpperCase() + k.slice(1));
    if (s) s.textContent = cd > 0.05 ? Math.ceil(cd) : "";
  });
}
function render(dt){
  dt = dt || 0.016;
  const w = cv.width = cv.clientWidth, h = cv.height = cv.clientHeight;
  cam.x += ((P.x - w / 2) - cam.x) * 0.12;
  cam.y += ((P.y - h / 2) - cam.y) * 0.12;
  // границы карты не показываем: камера упирается в края мира
  if (Math.abs(WORLD.w - Math.max(480, w)) > 40){
    WORLD.w = Math.max(480, w);
  }
  const maxX = Math.max(0, WORLD.w - w), maxY = Math.max(0, WORLD.h - h);
  cam.x = Math.max(0, Math.min(maxX, cam.x));
  cam.y = Math.max(0, Math.min(maxY, cam.y));
  ctx.fillStyle = "#1a2018"; ctx.fillRect(0, 0, w, h);
  ctx.save();
  ctx.translate(-cam.x + (FX.shakeX || 0), -cam.y + (FX.shakeY || 0));

  // земля: тёмная лесная подстилка (с запасом под тряску камеры)
  ctx.fillStyle = "#16210f"; ctx.fillRect(-64, -64, WORLD.w + 128, WORLD.h + 128);
  for (let y = -64; y < WORLD.h + 64; y += 64){
    for (let x = -64; x < WORLD.w + 64; x += 64){
      ctx.fillStyle = zoneAt(y).g; ctx.fillRect(x, y, 64, 64);

    }
  }
  if (TOWN.complete && TOWN.naturalWidth){
    ctx.save(); ctx.imageSmoothingEnabled = false; ctx.globalAlpha = 0.5;
    for (let gy = 0; gy < WORLD.h; gy += 32){
      for (let gx = 0; gx < WORLD.w; gx += 32){
        ctx.drawImage(TOWN, 0, 0, 16, 16, gx, gy, 32, 32);
      }
    }
    ctx.restore();
  }
  // декорации текущей локации
  const zc = zoneIndex(P.y);
  const zin = ZONES[zc];
  for (let d = 0; d < 70; d++){
    const hx = (d * 137 + zc * 53) % (WORLD.w - 80) + 40;
    const hy = zc * ZONE_H + (d * 71) % ZONE_H;
    if (d % 3 === 0){
      ctx.fillStyle = zin.a;
      ctx.beginPath(); ctx.arc(hx, hy, 5 + (d % 4), 0, 7); ctx.fill();
    } else if (d % 3 === 1){
      ctx.fillStyle = "#00000044";
      ctx.beginPath(); ctx.ellipse(hx, hy, 9, 6, 0, 0, 7); ctx.fill();
    } else {
      ctx.strokeStyle = zin.a; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(hx, hy); ctx.lineTo(hx - 3, hy - 10); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(hx, hy); ctx.lineTo(hx + 4, hy - 8); ctx.stroke();
    }
  }
  // тропа: пунктир из точек
  PATH.forEach(function(pt){
    ctx.beginPath();
    ctx.arc(pt.x, pt.y, 22, 0, 7);
    ctx.fillStyle = "#c9a06a";
    ctx.fill();
    ctx.beginPath();
    ctx.arc(pt.x, pt.y, 15, 0, 7);
    ctx.fillStyle = "#d9b47e";
    ctx.fill();
  });
  // здания и предметы деревни
  for (let zi = 0; zi < ZONES.length; zi++){
    const base = zi * ZONE_H;
    if (Math.abs(base - P.y) > ZONE_H * 1.5) continue;
    VILLAGE.forEach(function(v){
      const vy = base + v.y;
      const vx = (zi % 2) ? (WORLD.w - v.x) : v.x;
      if (v.kind === "cottage") drawFarm("cottage-blue", vx, vy, v.w, v.h);
      else if (v.kind === "lamp"){
        drawFarm("lamppost", vx, vy, v.w, v.h);
        FX.glowAt(vx, vy - v.h * 0.8, 160, "#ffcf7a", 0.5);
      }
      else if (v.kind === "bench") drawFarm("bench", vx, vy, v.w, v.h);
      else if (v.kind === "bed") drawFarm("flower-bed", vx, vy, v.w, v.h);
    });
  }
  // кусты/камни/трава под персонажем
  DECOR.forEach(function(d){
    if (d.k === "tree") return;
    if (d.k === "bush"){
      ctx.fillStyle = "#1e3818";
      ctx.beginPath(); ctx.arc(d.x, d.y - 6 * d.s, 13 * d.s, 0, 7); ctx.fill();
      ctx.fillStyle = "#2a5020";
      ctx.beginPath(); ctx.arc(d.x - 4 * d.s, d.y - 10 * d.s, 9 * d.s, 0, 7); ctx.fill();
    } else if (d.k === "rock"){
      ctx.fillStyle = "#3a3a44";
      ctx.beginPath(); ctx.ellipse(d.x, d.y, 11 * d.s, 8 * d.s, 0, 0, 7); ctx.fill();
      ctx.fillStyle = "#4c4c58";
      ctx.beginPath(); ctx.ellipse(d.x - 3 * d.s, d.y - 3 * d.s, 7 * d.s, 5 * d.s, 0, 0, 7); ctx.fill();
    } else {
      ctx.strokeStyle = "#2f4a1e"; ctx.lineWidth = 2;
      for (let g = -1; g <= 1; g++){
        ctx.beginPath(); ctx.moveTo(d.x + g * 4, d.y);
        ctx.lineTo(d.x + g * 6, d.y - 9 * d.s); ctx.stroke();
      }
    }
  });


  // арены боссов: пульсирующее кольцо, руны, прогресс ожидания
  bosses.forEach(function(bs){
    if (Math.abs(bs.y - P.y) > 1000) return;
    const pulse = 0.92 + Math.sin(animT * 2.4 + bs.idx * 1.7) * 0.08;
    FX.glowAt(bs.x, bs.y, bs.r * 2.8 * pulse, bs.t > 0 ? "#ff7a3c" : "#ff3b52", bs.t > 0 ? 0.5 : 0.36);
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    ctx.strokeStyle = "rgba(255,90,90,.5)"; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.arc(bs.x, bs.y, bs.r * pulse, 0, 7); ctx.stroke();
    ctx.strokeStyle = bs.t > 0 ? "rgba(255,214,120,.95)" : "rgba(255,154,60,.7)";
    ctx.lineWidth = 5;
    for (let s = 0; s < 2; s++){
      const a0 = animT * 1.9 + bs.idx + s * 3.14;
      ctx.beginPath(); ctx.arc(bs.x, bs.y, bs.r * 0.74, a0, a0 + 1.5); ctx.stroke();
    }
    if (bs.t > 0.01){
      ctx.strokeStyle = "#ffd98a"; ctx.lineWidth = 7;
      ctx.beginPath();
      ctx.arc(bs.x, bs.y, bs.r + 9, -1.5708, -1.5708 + 6.2832 * Math.min(1, bs.t / BOSS_WAIT));
      ctx.stroke();
    }
    ctx.restore();
    ctx.fillStyle = "#ffb4b4"; ctx.font = "bold 12px sans-serif"; ctx.textAlign = "center";
    ctx.fillText("БОСС " + (bs.idx + 1) + " · " + ZONES[bs.zone].n, bs.x, bs.y - 8);
    if (bs.t > 0.01){
      ctx.fillStyle = "#fff"; ctx.font = "900 22px ui-monospace,monospace";
      ctx.fillText(Math.ceil(BOSS_WAIT - bs.t), bs.x, bs.y + 30);
    }
  });

  // живые игроки: сглаженные позиции, анимация бега и удара
  Object.keys(REMOTE).forEach(function(key){
    drawRemote(REMOTE[key], animT);
  });
  // те, кто вышел: спят в углу своей локации
  drawOfflineAll(animT);
  drop.forEach(d => {
    FX.glowAt(d.x, d.y - 4, 60 + Math.sin(animT * 5) * 10, "#f6c94a", 0.8);
    ctx.fillStyle = "#f6c94a"; ctx.font = "16px sans-serif"; ctx.textAlign = "center";
    ctx.fillText("🗡", d.x, d.y);
    if (d.name){
      ctx.fillStyle = "#ffd9a0"; ctx.font = "7px 'Press Start 2P',monospace";
      ctx.fillText(d.name.slice(0, 18), d.x, d.y - 16);
    }
  });
  mobs.forEach(m => {
    ctx.save();
    ctx.translate(m.x, m.y);
    ctx.scale((m.sz || 1) * 1.25, (m.sz || 1) * 1.25);
    if (!drawTile(m.tile, 0, 0, 34, m.hit > 0 ? -2 : 0)){
      person(0, 0, m.hit > 0 ? "#ff8a8a" : (m.c || "#8a5a6a"));
    }
    ctx.restore();
    FX.glowAt(m.x, m.y - 8 * (m.sz || 1), 78 * (m.sz || 1),
              m.hit > 0 ? "#ff6a6a" : (m.c || "#8a5a6a"), m.hit > 0 ? 0.55 : 0.24);
    const bw = 36 * (m.sz || 1);
    ctx.fillStyle = "#000a"; ctx.fillRect(m.x - bw / 2, m.y - 40 * (m.sz || 1), bw, 5);
    ctx.fillStyle = "#e24646";
    ctx.fillRect(m.x - bw / 2, m.y - 40 * (m.sz || 1),
                 bw * Math.max(0, m.hp / m.max), 5);
  });
  FX.glowAt(P.x, P.y - 10, 140,
            P.weapon && P.weapon.kind === "staff" ? "#8fd8ff" :
            P.weapon && P.weapon.kind === "bow" ? "#8bd65a" : "#ffd98a", 0.3);
  drawHero(P.x, P.y, P.atkCd > 0.25);
  hits.forEach(h => {
    ctx.fillStyle = h.c; ctx.font = "bold 15px ui-monospace,monospace"; ctx.textAlign = "center";
    ctx.globalAlpha = Math.max(0, h.t); ctx.fillText(h.v, h.x, h.y); ctx.globalAlpha = 1;
  });
  FX.draw();
  FX.ambient(dt, cam.x, cam.y, w, h);
  ctx.restore();
  if (!FX.isGL()){
    const vg = ctx.createRadialGradient(w / 2, h / 2, Math.min(w, h) * 0.18,
                                        w / 2, h / 2, Math.max(w, h) * 0.72);
    vg.addColorStop(0, "rgba(0,0,0,0)");
    vg.addColorStop(0.45, "rgba(6,3,2,0.35)");
    vg.addColorStop(0.75, "rgba(6,3,2,0.70)");
    vg.addColorStop(1, "rgba(4,2,1,0.95)");
    ctx.fillStyle = vg;
    ctx.fillRect(0, 0, w, h);
    // общий тёмный тон
    ctx.fillStyle = "rgba(10,6,14,0.18)";
    ctx.fillRect(0, 0, w, h);
    FX.bloom2d();
  }
  FX.post();
  void h; void dtFix;
}
let dtFix = 0;
function refreshInv(){
  if (document.getElementById("cls").style.display !== "none") paintInv();
}
function paintInv(){
  const html = P.bag.map(id => {
    const w = weaponById(id);
    const on = P.weapon && P.weapon.id === id;
    return '<div class="c" data-eq="' + id + '" style="margin-bottom:8px;' +
      'border-color:' + (on ? "#3b6fff" : "#2a3346") + '">' +
      '<b>' + w.name + '</b><span>' + w.cls + ' · урон ' + w.dmg +
      ' · дальность ' + w.range + (on ? ' · В РУКАХ' : '') + '</span></div>';
  }).join("");
  ["inv", "inv2"].forEach(function(idd){
    const box = document.getElementById(idd);
    if (!box) return;
    box.innerHTML = html || '<div style="color:#8a7a9a;font-size:11px;padding:10px">' +
      'Пусто. Бей мобов — с них падает оружие.</div>';
    box.querySelectorAll("[data-eq]").forEach(el => el.onclick = () => {
      P.weapon = weaponById(el.dataset.eq);
      paintInv(); toast("Взял: " + P.weapon.name + " — теперь ты " + P.weapon.cls);
    });
  });
}
paintInv();
const bagBtn = document.getElementById("bagbtn");
if (bagBtn) bagBtn.onclick = (e) => {
  e.preventDefault();
  document.getElementById("bag").classList.add("on");
  paintInv();
};
const bag2 = document.getElementById("bag2");
if (bag2) bag2.onclick = () => {
  document.getElementById("bag").classList.add("on");
  paintInv();
};
const wUpg = document.getElementById("wupg");
if (wUpg) wUpg.onclick = () => heroUpgrade();
const wChat = document.getElementById("wchat");
if (wChat) wChat.onclick = () => chatOpen();
const wArmor = document.getElementById("warmor");
if (wArmor) wArmor.onclick = () => heroArmor();
const bagClose = document.getElementById("bagclose");
if (bagClose) bagClose.onclick = () => document.getElementById("bag").classList.remove("on");
document.getElementById("startbtn").onclick = () => {
  if (!P.started){
    reset();
    P.started = true;
    heroLoad();                 // прогресс подтянется, мобы пересоберутся по уровню
  }
  document.getElementById("cls").style.display = "none";
  if (!P.started2){ P.started2 = true; toast("Ты в подземелье. Фарми мобов"); }
};
const startLbl = document.getElementById("startbtn");
if (startLbl) startLbl.innerHTML = "<b>В бой</b>";
function openGfx(){
  const box = document.getElementById("gfx");
  if (!box) return;
  const names = [
    "БЫСТРОЕ · bloom на Canvas2D",
    "СРЕДНЕЕ · bloom 2 уровня, без зерна",
    "ВЫСОКОЕ · шейдеры + bloom 3 уровня"
  ];
  let html = '<div class="card"><h3>ГРАФИКА</h3>';
  [2, 1, 0].forEach(function(n){
    const on = FX.level === n;
    html += '<button data-fx="' + n + '" class="' + (on ? "on" : "") + '">' +
            (on ? "● " : "○ ") + names[n] + "</button>";
  });
  html += '<div class="fps">' + (FX.hasGL ? "WebGL работает" : "WebGL недоступен — только 2D") +
          "<br>FPS " + FX.fps + " · режим " + FX.level + "</div>";
  html += '<button data-fx="x" style="text-align:center;margin-top:10px">ЗАКРЫТЬ</button></div>';
  box.innerHTML = html;
  box.classList.add("on");
  box.querySelectorAll("[data-fx]").forEach(function(b){
    b.onclick = function(){
      const v = b.dataset.fx;
      if (v === "x"){ box.classList.remove("on"); return; }
      FX.setLevel(parseInt(v, 10));
      openGfx();
    };
  });
}
document.querySelectorAll(".top [data-tab]").forEach(b => b.onclick = () => {
  const t = b.dataset.tab;
  if (t === "bag"){ document.getElementById("bag").classList.add("on"); paintInv(); return; }
  if (t === "clicker"){ location.href = "/yugi"; return; }
  if (t === "quests"){ toast("Задания — заглушка прототипа"); return; }
  if (t === "board"){ openTop(); return; }
  if (t === "settings"){ openGfx(); return; }
});
function sync(){ document.getElementById("coins").textContent = P.coins;
  if (P.weapon){
    const el = document.getElementById("wname");
    if (el) el.textContent = P.weapon.name;
    const e2 = document.getElementById("wcls");
    if (e2) e2.textContent = P.weapon.cls;
    const e3 = document.getElementById("wdmg");
    if (e3) e3.textContent = P.weapon.dmg;
    const e4 = document.getElementById("wrange");
    if (e4) e4.textContent = P.weapon.range;
    const e5 = document.getElementById("wspd");
    if (e5) e5.textContent = P.weapon.spd || 1;
  }
  const armorBtn = document.getElementById("warmor");
  if (armorBtn){
    armorBtn.textContent = HERO_ARMOR
      ? ("БРОНЯ · " + HERO_ARMOR.price + " ЮГОВ · −" + Math.round((HERO_ARMOR.discount || 0) * 100) + "%")
      : ("БРОНЯ " + (P.armor || 0) + " · МАКС");
  }
  const up = document.getElementById("wupg");
  if (up){
    up.textContent = HERO_OFFER ? ("УЛУЧШИТЬ · " + HERO_OFFER.price) : "УЛУЧШИТЬ";
    up.disabled = !HERO_OFFER || P.coins < HERO_OFFER.price;
  }
  const zi = zoneIndex(P.y);
  const zel = document.getElementById("zone");
  if (zel) zel.textContent = "ЛОК. " + (zi + 1) + "/10 · " + ZONES[zi].n + " · ур." + (1 + zi * 25); }
requestAnimationFrame(loop);
</script>
</body>
</html>
"""


@router.get("/proto_dungeon", response_class=HTMLResponse)
async def proto_dungeon() -> HTMLResponse:
    """Прототип «Подземелья Тимура»: карта, мобы, кооп-босс.

    Экономику не трогает: пишет только в dungeon_boss / dungeon_boss_players.
    """
    return HTMLResponse(DUNGEON_PAGE)

# --------------------------------------------------------------------------- #
# Кооп-босс подземелья: один босс на двоих
# --------------------------------------------------------------------------- #
#
# Состояние живёт в dungeon_boss / dungeon_boss_players. Бой симулируется
# лениво: каждая ручка сначала догоняет бой до текущего момента (старт по
# времени, удары босса), поэтому планировщик не нужен.


async def _json_body(request: Request) -> dict[str, Any]:
    """Тело запроса как словарь; мусор и пустое тело — пустой словарь."""
    try:
        body = await request.json()
    except (TypeError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


async def _dungeon_boss(request: Request):
    """Игрок и репозиторий кооп-босса — общая часть для всех ручек."""
    user = await _player(request)
    repo = getattr(request.app.state, "dungeon", None)
    if repo is None:
        raise DungeonError("Кооп-босс ещё не включён")
    return user, repo


@router.post("/api/dungeon/boss/join")
async def api_dungeon_boss_join(request: Request) -> JSONResponse:
    """Открыть комнату на точке или занять второе место в чужой."""
    try:
        user, repo = await _dungeon_boss(request)
        body = await _json_body(request)
        room = await repo.join(int(user["id"]), body.get("zone"), datetime.now(timezone.utc))
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)
    except DungeonError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    return JSONResponse({"ok": True, "boss": room})


@router.get("/api/dungeon/boss/state")
async def api_dungeon_boss_state(request: Request) -> JSONResponse:
    """Опрос состояния: страница тянет его раз в секунду."""
    try:
        user, repo = await _dungeon_boss(request)
        room = await repo.state(int(user["id"]), datetime.now(timezone.utc))
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)
    except DungeonError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    return JSONResponse({"ok": True, "boss": room})


@router.post("/api/dungeon/boss/hit")
async def api_dungeon_boss_hit(request: Request) -> JSONResponse:
    """Удар по общему боссу. Урон присылает страница — как и в прототипе."""
    try:
        user, repo = await _dungeon_boss(request)
        body = await _json_body(request)
        room = await repo.hit(
            int(user["id"]), body.get("damage"), datetime.now(timezone.utc)
        )
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)
    except DungeonError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    return JSONResponse({"ok": True, "boss": room})


@router.post("/api/dungeon/boss/leave")
async def api_dungeon_boss_leave(request: Request) -> JSONResponse:
    """Выйти из боя: второй игрок остаётся драться один."""
    try:
        user, repo = await _dungeon_boss(request)
        result = await repo.leave(int(user["id"]), datetime.now(timezone.utc))
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)
    except DungeonError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    return JSONResponse({"ok": True, "left": result})

@router.post("/api/dungeon/boss/start")
async def api_dungeon_boss_start(request: Request) -> JSONResponse:
    """Начать бой, не дожидаясь окна: игрок не хочет ждать напарника."""
    try:
        user, repo = await _dungeon_boss(request)
        room = await repo.start_now(int(user["id"]), datetime.now(timezone.utc))
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)
    except DungeonError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    return JSONResponse({"ok": True, "boss": room})

@router.post("/api/dungeon/presence")
async def api_dungeon_presence(request: Request) -> JSONResponse:
    """Запасной путь без сокета: своя точка на карте и чужие в ответ.

    Основной транспорт — /ws/dungeon: там 10 тактов в секунду и никакой
    базы. Здесь то же самое, но по HTTP, если сокет не поднялся.
    """
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)

    hub = getattr(state, "hub", None)
    if hub is None:
        return JSONResponse({"error": "Карта ещё не включена"}, status_code=400)
    user_id = int(user["id"])
    name = str(user.get("first_name") or user.get("username") or "Игрок")
    spot = hub.touch(user_id, name, await _json_body(request))
    hub.prune()
    await _save_spot(state, user_id, spot)
    return JSONResponse(
        {
            "ok": True,
            "players": hub.snapshot(user_id),
            "offline": await _offline_rows(state),
        }
    )


async def _dungeon_broadcast(hub, message: dict) -> None:
    """Разослать кадр всем, кто на карте; отвалившиеся сокеты убрать."""
    dead = []
    for socket in list(hub.sockets):
        try:
            await socket.send_json(message)
        except Exception:  # noqa: BLE001 - сокет мог закрыться
            dead.append(socket)
    for socket in dead:
        hub.leave_socket(socket)


# Оффлайн-игроки нужны всем сразу: держим один запрос на 4 секунды.
_OFFLINE_CACHE: dict[str, Any] = {"at": 0.0, "rows": []}
_LAST_SPOT: dict[int, float] = {}


async def _offline_rows(state) -> list[dict]:
    """Кто вышел — аватаром в углу своей локации. Кэш на 4 секунды."""
    import time

    now = time.monotonic()
    if now - float(_OFFLINE_CACHE["at"]) < 4.0:
        return _OFFLINE_CACHE["rows"]  # type: ignore[return-value]
    repo = getattr(state, "hero", None)
    rows: list[dict] = []
    if repo is not None:
        with contextlib.suppress(Exception):
            rows = await repo.offline(24)
    _OFFLINE_CACHE["at"] = now
    _OFFLINE_CACHE["rows"] = rows
    return rows


async def _save_spot(state, user_id: int, spot, force: bool = False) -> None:
    """Пишем последнюю точку не чаще раза в 20 секунд и всегда при выходе."""
    import time

    if spot is None:
        return
    repo = getattr(state, "hero", None)
    if repo is None:
        return
    now = time.monotonic()
    if not force and now - float(_LAST_SPOT.get(user_id, 0.0)) < 20.0:
        return
    _LAST_SPOT[user_id] = now
    with contextlib.suppress(Exception):
        await repo.save_spot(user_id, spot.zone, spot.x, spot.y)


@router.websocket("/ws/dungeon")
async def ws_dungeon(websocket: WebSocket) -> None:
    """Живая карта по сокету: 10 тактов в секунду, база не участвует.

    Первое сообщение несёт подпись initData — по ней и пускаем. Дальше в
    каждом сообщении своя позиция, в ответ — чужие точки рядом.
    """
    state = websocket.app.state
    hub = getattr(state, "hub", None)
    if hub is None:
        await websocket.close(code=1011)
        return
    await websocket.accept()
    hub.join_socket(websocket)
    user_id = 0
    name = "Игрок"
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            if not user_id:
                found = check_init_data(
                    str(data.get("init") or ""), state.settings.bot_token
                )
                if not found or not found.get("id"):
                    await websocket.send_json({"error": "Открой карту через бота"})
                    await websocket.close(code=1008)
                    return
                user_id = int(found["id"])
                name = str(found.get("first_name") or found.get("username") or "Игрок")
                with contextlib.suppress(Exception):
                    await state.db.ensure_player(
                        user_id, found.get("username"), found.get("first_name")
                    )
            if data.get("type") == "chat":
                text = " ".join(str(data.get("text") or "").split())[:dungeon.CHAT_MAX]
                if text and hub.can_talk(user_id):
                    await _dungeon_broadcast(
                        hub,
                        {"type": "chat", "id": user_id, "name": name, "text": text},
                    )
                continue
            spot = hub.touch(user_id, name, data)
            await _save_spot(state, user_id, spot)
            await websocket.send_json(
                {
                    "ok": True,
                    "players": hub.snapshot(user_id),
                    "offline": await _offline_rows(state),
                }
            )
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 - сокет мог отвалиться на любом шаге
        log.debug("Сокет карты упал", exc_info=True)
    finally:
        hub.leave_socket(websocket)
        if user_id:
            spot = hub.snapshot_spot(user_id)
            hub.drop(user_id)          # сначала перестаём быть «живым»
            await _save_spot(state, user_id, spot, force=True)

@router.get("/api/dungeon/hero")
async def api_dungeon_hero(request: Request) -> JSONResponse:
    """Прогресс героя: уровень, монеты, сумка и оружие в руках."""
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)
    repo = getattr(state, "hero", None)
    if repo is None:
        return JSONResponse({"error": "Прогресс ещё не включён"}, status_code=400)
    hero = await repo.load(int(user["id"]))
    return JSONResponse({"ok": True, "hero": hero})


@router.post("/api/dungeon/hero")
async def api_dungeon_hero_save(request: Request) -> JSONResponse:
    """Сохранить прогресс. Всё приходит с клиента и режется в dungeon_hero."""
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)
    repo = getattr(state, "hero", None)
    if repo is None:
        return JSONResponse({"error": "Прогресс ещё не включён"}, status_code=400)
    hero = await repo.save(int(user["id"]), await _json_body(request))
    return JSONResponse({"ok": True, "hero": hero})

@router.post("/api/dungeon/upgrade")
async def api_dungeon_upgrade(request: Request) -> JSONResponse:
    """Улучшить оружие за монеты: цена и списание — на сервере."""
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)
    repo = getattr(state, "hero", None)
    if repo is None:
        return JSONResponse({"error": "Прогресс ещё не включён"}, status_code=400)
    body = await _json_body(request)
    try:
        hero = await repo.upgrade(int(user["id"]), body.get("weapon"))
    except DungeonError as error:
        return JSONResponse({"ok": False, "error": str(error)}, status_code=400)
    return JSONResponse({"ok": True, "hero": hero})


@router.get("/api/dungeon/top")
async def api_dungeon_top(request: Request) -> JSONResponse:
    """Таблица лидеров подземелья: уровень, убийства, монеты."""
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)
    repo = getattr(state, "hero", None)
    if repo is None:
        return JSONResponse({"error": "Лидеры ещё не включены"}, status_code=400)
    players = await repo.top(10)
    return JSONResponse({"ok": True, "players": players, "me": int(user["id"])})


@router.post("/api/dungeon/armor")
async def api_dungeon_armor(request: Request) -> JSONResponse:
    """Броня за Юги кликера: снимает урон босса."""
    state = request.app.state
    try:
        user = await _player(request)
    except ShopError as error:
        return JSONResponse({"error": str(error)}, status_code=401)
    repo = getattr(state, "hero", None)
    if repo is None:
        return JSONResponse({"error": "Броня ещё не включена"}, status_code=400)
    try:
        hero = await repo.buy_armor(int(user["id"]))
    except DungeonError as error:
        return JSONResponse({"ok": False, "error": str(error)}, status_code=400)
    return JSONResponse({"ok": True, "hero": hero})
