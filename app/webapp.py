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

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from . import buyer
from . import cases as cases_mod
from . import roulette as roulette_mod
from . import upgrader
from .cards import CARDS, CARDS_BY_ID, get_card, image_url, rarity_name
from .cases import roll_case_card
from .games_page import CASE_PAGE, ROULETTE_PAGE
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
    '</span><span>✨ ' + c.ability + ' (КД ' + c.cooldown + ')' +
    (c.effects ? ': ' + c.effects : '') + '</span></div>' : "";
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
    return HTMLResponse(CASE_PAGE)


@router.get("/roulette_app", response_class=HTMLResponse)
async def roulette_app_page() -> HTMLResponse:
    return HTMLResponse(ROULETTE_PAGE)


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
    return JSONResponse(
        {
            "cases": len(cases),
            "pool": cases_mod.case_pool(),
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
    if not await state.db.open_case(uid, int(case["id"])):
        return JSONResponse({"error": "Этот кейс уже открыт"}, status_code=400)
    card = roll_case_card()
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
            "count": count,
        }
    )


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
    return HTMLResponse(MARKET_PAGE)


@router.get("/stocks", response_class=HTMLResponse)
async def stocks_app() -> HTMLResponse:
    return HTMLResponse(STOCKS_PAGE)


STOCKS_PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Северо-Юг · Биржа</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{
  --bg:#0f1117; --card:#171a23; --line:#252a38; --ink:#e8ebf2; --muted:#8b93a7;
  --up:#22c55e; --down:#ef4444; --accent:#4f46e5; --accent-soft:#1e2140;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg);color:var(--ink);min-height:100vh;padding-bottom:100px}
header{position:sticky;top:0;z-index:5;background:rgba(15,17,23,.94);
  backdrop-filter:saturate(180%) blur(12px);border-bottom:1px solid var(--line);
  padding:14px 16px;display:flex;align-items:baseline;justify-content:space-between;gap:12px}
h1{margin:0;font-size:19px;letter-spacing:-.2px}
.wallet{font-weight:700;font-size:15px;background:var(--accent-soft);color:#c7c9ff;
  border-radius:999px;padding:7px 14px;white-space:nowrap}
main{padding:12px 14px}
.pf{background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:12px 14px;margin-bottom:12px;font-size:14px;color:var(--muted)}
.pf b{color:var(--ink)}
.pf.warn{color:#fecaca;border-color:#7f1d1d;background:#2a1416}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;
  padding:12px;margin-bottom:12px}
.top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}
.name{font-weight:700;font-size:15px}
.price{font-size:14px;margin-top:4px;color:var(--muted)}
.price b,.price .up,.price .down{font-weight:700}
.buycell{font-size:11px;color:var(--muted);text-align:right;line-height:1.6;white-space:nowrap}
.bars{display:flex;gap:2px;margin-top:10px;height:30px;align-items:flex-end}
.bars i{flex:1 1 0;min-width:2px;border-radius:2px;background:#3a4055;height:6px}
.bars i.up{background:var(--up)}
.bars i.down{background:var(--down)}
.bars i.flat{background:#3a4055}
.row{cursor:pointer}
.chev{color:var(--muted);font-size:24px;line-height:1;padding-left:6px}
.back{background:transparent;border:1px solid var(--line);color:var(--muted);
  border-radius:10px;padding:9px 12px;font-size:13px;margin-bottom:12px}
.name.big{font-size:18px}
.price.big{font-size:16px}
.chart{width:100%;height:170px;display:block;margin-top:12px}
.axis{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);margin-top:4px}
.deals{font-size:12px;color:var(--muted);margin-top:10px}
.deals b{color:var(--ink)}
.tag{font-size:11px;color:#c7c9ff;background:var(--accent-soft);border-radius:999px;padding:2px 8px;margin-left:6px}
.tag.hot{color:#fecaca;background:#7f1d1d}
.hint{font-size:12px;color:var(--muted);margin-top:12px;height:60px;display:flex;align-items:center}
.spikes{font-size:12px;color:var(--muted);margin-top:8px;line-height:1.6}
.btn:disabled{opacity:.45}
.mine{margin-top:9px;font-size:12px;color:var(--muted)}
.up{color:var(--up)} .down{color:var(--down)}
.hint-inline{font-size:11px;color:var(--muted)}
.act{display:flex;gap:8px;margin-top:11px}
.qty{width:74px;background:#0d0f16;border:1px solid var(--line);color:var(--ink);
  border-radius:10px;padding:10px;font-size:14px;text-align:center}
.btn{flex:1;border:0;border-radius:10px;padding:11px;font-size:14px;font-weight:700;color:#fff}
.btn.buy{background:linear-gradient(135deg,#16a34a,#15803d)}
.btn.sell{background:linear-gradient(135deg,#dc2626,#b91c1c)}
.btn:active{transform:scale(.98)}
#toast{position:fixed;left:14px;right:14px;bottom:18px;background:#232838;color:#fff;
  border-radius:12px;padding:14px 16px;font-size:14px;line-height:1.45;
  transform:translateY(150%);transition:.26s cubic-bezier(.2,.8,.3,1);z-index:9}
#toast.on{transform:translateY(0)}
#toast.ok{background:#15803d}
#toast.bad{background:#b91c1c}
</style>
</head>
<body>
<header>
  <h1>📈 Биржа</h1>
  <div class="wallet">💰 <span id="balance">…</span></div>
</header>
<main id="list"><div class="pf">Загружаю курсы…</div></main>
<div id="toast"></div>
<script>
const tg = window.Telegram ? window.Telegram.WebApp : null;
const headers = {"X-Telegram-Init-Data": tg ? tg.initData : "", "Content-Type":"application/json"};
let state = {stocks: [], portfolio: {}, balance: 0, selected: null, tickAge: 0};
let maxPerStock = 100;

function money(n){ return String(Math.round(Number(n)||0)).replace(/\B(?=(\d{3})+(?!\d))/g, " "); }
function esc(s){ return String(s).replace(/[<>&]/g, c => ({"<":"&lt;",">":"&gt;","&":"&amp;"}[c])); }
function toast(t,k){ var el=document.getElementById("toast"); el.textContent=t;
  el.className="on "+(k||""); clearTimeout(el._t); el._t=setTimeout(function(){el.className="";},3200); }

// Мини-столбики в списке: высота зависит от курса, цвет — от шага.
function bars(hist){
  if(!hist || hist.length < 2) return "";
  var min = Math.min.apply(null, hist), max = Math.max.apply(null, hist);
  var range = Math.max(1, max - min);
  var out = "";
  for(var i=0;i<hist.length;i++){
    var prev = i ? hist[i-1] : hist[i];
    var h = 6 + Math.round(22 * (hist[i] - min) / range);
    var cls = hist[i] > prev ? "up" : (hist[i] < prev ? "down" : "flat");
    out += '<i class="'+cls+'" style="height:'+h+'px" title="'+hist[i]+'"></i>';
  }
  return '<div class="bars">'+out+'</div>';
}

// Настоящий график курса: линия по точкам, масштаб по минимуму и максимуму.
function lineChart(hist, spikes){
  if(!hist || hist.length < 2) return '<div class="hint">Мало данных — подожди пару шагов курса…</div>';
  var W = 320, H = 150, pad = 4;
  var min = Math.min.apply(null, hist), max = Math.max.apply(null, hist);
  if(min === max){ min -= 1; max += 1; }
  var n = hist.length;
  function px(i){ return pad + i * (W - 2*pad) / (n - 1); }
  function py(v){ return pad + (max - v) * (H - 2*pad) / (max - min); }
  var pts = [];
  for(var i=0;i<n;i++){ pts.push(px(i).toFixed(1)+","+py(hist[i]).toFixed(1)); }
  var line = pts.join(" ");
  var up = hist[n-1] >= hist[0];
  var color = up ? "#22c55e" : "#ef4444";
  var area = (pad)+","+(H-pad)+" "+line+" "+(W-pad)+","+(H-pad);
  var grid = "";
  for(var g=0; g<=4; g++){
    var gy = (pad + g*(H-2*pad)/4).toFixed(1);
    grid += '<line x1="0" y1="'+gy+'" x2="'+W+'" y2="'+gy+'" stroke="#232838" stroke-width="1"/>';
  }
  // Отмечаем резкие скачки: колечко вокруг точки, зелёное вверх / красное вниз.
  var marks = "";
  (spikes || []).forEach(function(sp){
    var si = Number(sp.i);
    if(!(si >= 0 && si < n)) return;
    var sc = Number(sp.change) >= 0 ? "#22c55e" : "#ef4444";
    marks += '<circle cx="'+px(si).toFixed(1)+'" cy="'+py(hist[si]).toFixed(1)+'" r="3.4" '+
      'fill="#0f1117" stroke="'+sc+'" stroke-width="2"/>';
  });
  return '<svg class="chart" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none">'+
    grid +
    '<polygon points="'+area+'" fill="'+color+'" opacity="0.13"/>'+
    '<polyline points="'+line+'" fill="none" stroke="'+color+'" stroke-width="2.5" '+
      'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>'+
    marks +
    '<circle cx="'+px(n-1).toFixed(1)+'" cy="'+py(hist[n-1]).toFixed(1)+'" r="3" fill="'+color+'"/>'+
  '</svg>';
}

function agoText(sec){
  sec = Number(sec) || 0;
  if(sec < 60) return "только что";
  if(sec < 3600) return Math.floor(sec/60)+" мин назад";
  return Math.floor(sec/3600)+" ч назад";
}

function spikesLine(spikes){
  if(!spikes || !spikes.length){
    return '<div class="spikes">Резких скачков за это время не было.</div>';
  }
  var parts = [];
  var list = spikes.slice(-4).reverse();
  for(var i=0;i<list.length;i++){
    var sp = list[i];
    var up = Number(sp.change) >= 0;
    parts.push('<span class="'+(up?"up":"down")+'">'+(up?"▲":"▼")+' '+
      Number(sp.change).toFixed(1)+'%</span> '+agoText(sp.ago));
  }
  return '<div class="spikes">Скачки: '+parts.join(" · ")+'</div>';
}

// Строка списка: тапаешь — открывается график монеты.
function row(s){
  var up = s.change >= 0;
  var tag = (s.pump ? '<span class="tag hot">🔥 памп!</span>' : "") +
    (s.my_shares > 0 ? '<span class="tag">'+s.my_shares+' шт.</span>' : "");
  return '<div class="card row" data-open="'+s.slug+'">'+
    '<div class="top"><div><div class="name">'+s.emoji+' '+esc(s.name)+tag+'</div>'+
    '<div class="price"><b>'+money(s.price)+'</b> <span class="'+(up?"up":"down")+'">'+(up?"▲":"▼")+' '+Number(s.change).toFixed(2)+'%</span></div></div>'+
    '<div class="chev">›</div></div>'+
    bars(s.history)+
  '</div>';
}

// Карточка монеты с большим графиком и сделками.
function detail(s){
  var up = s.change >= 0;
  var hist = s.history || [];
  var min = hist.length ? Math.min.apply(null, hist) : s.price;
  var max = hist.length ? Math.max.apply(null, hist) : s.price;
  var mine = "";
  if(s.my_shares > 0){
    var pnl = s.my_pnl >= 0 ? '<span class="up">+'+money(s.my_pnl)+'</span>' : '<span class="down">'+money(s.my_pnl)+'</span>';
    var pct = s.my_spent > 0 ? ' ('+(s.my_pnl/s.my_spent*100).toFixed(1)+'%)' : "";
    mine = '<div class="mine">У тебя: <b>'+s.my_shares+'</b> шт. · '+money(s.my_value)+' · '+pnl+pct+'</div>';
  }
  return '<button class="back" data-back="1">← Все монеты</button>'+
    '<div class="card">'+
      '<div class="name big">'+s.emoji+' '+esc(s.name)+(s.pump ? ' <span class="tag hot">🔥 памп!</span>' : '')+'</div>'+
      '<div class="price big"><b>'+money(s.price)+'</b> <span class="'+(up?"up":"down")+'">'+(up?"▲":"▼")+' '+Number(s.change).toFixed(2)+'%</span> <span class="hint-inline">за 15 мин</span></div>'+
      lineChart(hist, s.spikes)+
      '<div class="axis"><span>мин '+money(min)+'</span><span>макс '+money(max)+'</span></div>'+
      spikesLine(s.spikes)+
      '<div class="deals">купить <b>'+money(s.buy_price)+'</b> · продать <b>'+money(s.sell_price)+'</b></div>'+
      '<div class="deals">'+(s.room > 0
          ? 'Лимит '+maxPerStock+' шт. на монету · можно докупить ещё '+s.room
          : 'Лимит '+maxPerStock+' шт. достигнут')+'</div>'+
      mine+
      '<div class="act"><input class="qty" type="number" min="1" value="1" data-qty="'+s.slug+'">'+
      '<button class="btn buy" data-buy="'+s.slug+'"'+(s.room > 0 ? "" : " disabled")+'>Купить</button>'+
      '<button class="btn sell" data-sell="'+s.slug+'">Продать</button></div>'+
    '</div>';
}

function render(){
  document.getElementById("balance").textContent = money(state.balance);
  var pf = state.portfolio || {};
  var pnl = (pf.pnl||0) >= 0 ? '<span class="up">+'+money(pf.pnl||0)+'</span>' : '<span class="down">'+money(pf.pnl||0)+'</span>';
  var head = '<div class="pf">Портфель: <b>'+money(pf.value||0)+'</b> · вложено '+money(pf.spent||0)+' · '+pnl+'</div>';
  if(state.tickAge > 120){
    head = '<div class="pf warn">⚠️ Курс не обновлялся уже '+Math.floor(state.tickAge/60)+
      ' мин. Если так и стоит — напиши админу: <b>/admin stock fix</b></div>' + head;
  }
  var box = document.getElementById("list");
  var stock = null;
  if(state.selected){
    for(var i=0;i<state.stocks.length;i++){
      if(state.stocks[i].slug === state.selected){ stock = state.stocks[i]; break; }
    }
  }
  if(stock){
    box.innerHTML = head + detail(stock);
  } else {
    state.selected = null;
    box.innerHTML = head + state.stocks.map(row).join("");
  }
  bind();
}

function bind(){
  document.querySelectorAll("[data-open]").forEach(function(el){
    el.onclick = function(){ state.selected = el.dataset.open; render(); };
  });
  var back = document.querySelector("[data-back]");
  if(back){ back.onclick = function(){ state.selected = null; render(); }; }
  document.querySelectorAll("[data-buy]").forEach(function(b){ b.onclick=function(){ trade("buy", b.dataset.buy); }; });
  document.querySelectorAll("[data-sell]").forEach(function(b){ b.onclick=function(){ trade("sell", b.dataset.sell); }; });
}

async function load(){
  try{
    var r = await fetch("/api/stocks", {headers});
    var d = await r.json();
    if(d.error){ toast(d.error,"bad"); return; }
    state.stocks = d.stocks; state.portfolio = d.portfolio; state.balance = d.me.balance;
    state.tickAge = d.tick_age || 0;
    if(d.limits && d.limits.max_per_stock) maxPerStock = d.limits.max_per_stock;
    render();
  }catch(e){ toast("Не смог загрузить биржу","bad"); }
}

async function trade(kind, slug){
  var input = document.querySelector('[data-qty="'+slug+'"]');
  var shares = Math.max(1, Math.floor(Number(input ? input.value : 1) || 1));
  try{
    var r = await fetch("/api/stocks/"+kind, {method:"POST", headers, body: JSON.stringify({slug: slug, shares: shares})});
    var d = await r.json();
    if(d.error){ toast(d.error,"bad"); }
    else{
      toast((kind==="buy"?"Куплено ":"Продано ")+shares+" за "+money(d.total), "ok");
      if(tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
    }
  }catch(e){ toast("Связь потерялась","bad"); }
  await load();
}

if(tg){ tg.ready(); tg.expand(); }
load();
setInterval(load, 15000);
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
  position:sticky;top:0;z-index:5;background:rgba(246,246,248,.92);
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
  border:1px solid var(--line);background:#fff;color:var(--muted);border-radius:10px;
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
.stats{display:flex;gap:12px;margin-top:7px;font-size:13px;font-weight:600;color:#374151}
.seller{font-size:12px;color:var(--muted);margin-top:6px}
.bottom{
  display:flex;align-items:center;justify-content:space-between;gap:10px;
  padding:11px 12px;border-top:1px solid var(--line);background:#fcfcfd
}
.price{font-weight:800;font-size:16px;color:var(--ink)}
.btn{
  border:0;border-radius:11px;padding:11px 18px;font-size:14px;font-weight:700;
  color:#fff;background:var(--accent);transition:.15s
}
.btn:active{transform:scale(.98)}
.btn.ghost{background:#fff;color:var(--bad);border:1px solid var(--line)}
.btn[disabled]{background:#e9eaee;color:#9aa0aa}
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
    document.getElementById("balance").textContent = money(state.balance);
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
    targets = [upgrader.card_payload(card) for card in CARDS]
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
        odd = upgrader.chance(source, target)
        won = upgrader.roll(source, target)

        user_id = int(user["id"])
        ok = await state.db.run_upgrade(user_id, from_id, to_id, odd, won)
        if not ok:
            raise ValueError("Этой карты у тебя уже нет.")
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
        }
    )


@router.get("/upgrader", response_class=HTMLResponse)
async def upgrader_app() -> HTMLResponse:
    return HTMLResponse(UPGRADER_PAGE)






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

.stage{margin:16px 0 6px;position:relative;display:flex;align-items:center;justify-content:center}
.wheelbox{position:relative;width:290px;height:290px;max-width:84vw;max-height:84vw}
.pointer{position:absolute;top:-2px;left:50%;transform:translateX(-50%);z-index:5;
  width:0;height:0;border-left:11px solid transparent;border-right:11px solid transparent;
  border-top:20px solid var(--acc2);filter:drop-shadow(0 2px 6px rgba(0,0,0,.65))}
.pointer::after{content:"";position:absolute;top:-7px;left:-5px;width:10px;height:10px;border-radius:50%;
  background:var(--acc2);box-shadow:0 0 10px rgba(255,197,61,.8)}
.wheel{position:absolute;inset:0;border-radius:50%;
  background:radial-gradient(circle at 50% 50%,#10141d 58%,#161b26 59%,#161b26 100%);
  border:5px solid #212836;box-shadow:inset 0 0 40px rgba(0,0,0,.75),0 0 30px rgba(0,0,0,.5);
  transition:transform 4.6s cubic-bezier(.12,.72,.06,1)}
.chip{position:absolute;top:50%;left:50%;width:46px;height:46px;margin:-23px 0 0 -23px;
  border-radius:10px;background:var(--panel2);border:2px solid #2b3446;
  display:flex;align-items:center;justify-content:center;font-size:20px;overflow:hidden}
.chip.win{border-color:var(--acc);box-shadow:0 0 12px rgba(245,158,11,.45)}
.chip img{width:100%;height:100%;object-fit:cover}
.hub{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
  width:118px;height:118px;border-radius:50%;background:#0d1119;border:2px solid #232b3c;
  display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;z-index:4}
.hub .v{font-size:27px;font-weight:900;letter-spacing:-.5px}
.hub .w{font-size:9.5px;color:var(--muted);text-align:center;padding:0 8px;line-height:1.3}
.hub .t{font-size:10px;color:var(--muted)}

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
.card .ct{position:absolute;top:4px;right:5px;font-size:9.5px;font-weight:700;color:#dbe3ef;
  background:rgba(0,0,0,.6);border-radius:6px;padding:1px 5px}
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
    <div class="wheelbox">
      <div class="pointer"></div>
      <div class="wheel" id="wheel"></div>
      <div class="hub">
        <div class="v" id="pct">—</div>
        <div class="w" id="word">выбери карты</div>
      </div>
    </div>
  </div>

  <div class="tabs">
    <button class="tab on" data-tab="mine" id="tabMine">Мои карты</button>
    <button class="tab" data-tab="targets" id="tabTargets">Вы получите</button>
  </div>
  <div class="cards" id="grid"></div>
</div>

<button class="go" id="go" disabled>УЛУЧШИТЬ</button>

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
let S = {mine: [], targets: [], ladder: [], steps: {}, A: null, B: null, tab: "mine", busy: false};

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
// Какие сектора считаются выигрышными: размазаны по кругу, а не кучей.
function isWin(i, wins){ return wins > 0 && (i * wins) % SEGMENTS < wins; }
function buildWheel(wins, art){
  const wheel = document.getElementById("wheel");
  wheel.style.transition = "none";
  wheel.style.transform = "rotate(0deg)";
  let html = "";
  for (let i = 0; i < SEGMENTS; i++){
    const angle = i * (360 / SEGMENTS);
    const win = isWin(i, wins);
    const inner = win && art
      ? '<img src="' + art + '" alt="">'
      : (win ? "🎁" : "💀");
    html += '<div class="chip' + (win ? " win" : "") + '" style="transform:rotate(' + angle +
      'deg) translateY(-112px) rotate(' + (-angle) + 'deg)">' + inner + '</div>';
  }
  wheel.innerHTML = html;
  void wheel.offsetWidth;
  wheel.style.transition = "";
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
      if (S.A && S.B) buildWheel(winsFor(chanceOf(S.A, S.B)), S.B.image);
      else buildWheel(0, null);
      if (S.tab === "mine" && S.A) { S.tab = "targets"; render(); }
    };
  });
}
function winsFor(chance){ return Math.max(1, Math.min(SEGMENTS - 1, Math.round(chance * SEGMENTS))); }

async function load(){
  try{
    const r = await fetch("/api/upgrader", {headers});
    const d = await r.json();
    if (d.error){ toast(d.error, true); return; }
    S.mine = d.mine; S.targets = d.targets; S.ladder = d.ladder; S.steps = d.steps;
    document.getElementById("bal").textContent = money(d.me.balance) + " очк.";
    if (S.A && !S.mine.some(c => c.id === S.A.id)) S.A = null;
    if (S.B && !S.targets.some(c => c.id === S.B.id)) S.B = null;
    if (!S.A && S.mine.length) S.A = S.mine[0];
    render();
    if (S.A && S.B) buildWheel(winsFor(chanceOf(S.A, S.B)), S.B.image); else buildWheel(0, null);
  }catch(e){ toast("Не смог загрузить", true); }
}
async function spin(){
  if (S.busy || !S.A || !S.B) return;
  S.busy = true; render();
  const odd = chanceOf(S.A, S.B);
  try{
    const r = await fetch("/api/upgrader/spin", {method:"POST", headers,
      body: JSON.stringify({from: S.A.id, to: S.B.id})});
    const d = await r.json();
    if (d.error){ toast(d.error, true); S.busy = false; await load(); return; }

    // Собираем барабан под результат: сколько секторов выигрышных.
    const wins = winsFor(d.chance);
    buildWheel(wins, d.to.image);
    const pool = [];
    for (let i = 0; i < SEGMENTS; i++) if (isWin(i, wins) === d.won) pool.push(i);
    const seg = pool[Math.floor(Math.random() * pool.length)];
    const step = 360 / SEGMENTS;
    const jitter = (Math.random() - 0.5) * step * 0.6;
    const turns = 5 + Math.floor(Math.random() * 2);
    const wheel = document.getElementById("wheel");
    wheel.style.transform = "rotate(" + (360 * turns - seg * step + jitter) + "deg)";
    if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("medium");

    await new Promise(res => setTimeout(res, 4800));
    document.getElementById("rIcon").textContent = d.won ? "🎉" : "💀";
    document.getElementById("rArt").innerHTML = d.won && d.to.image
      ? '<img src="' + d.to.image + '" alt="">' : "";
    document.getElementById("rTitle").textContent = d.won ? esc(d.to.name) + " — твоя!" : "Не повезло";
    document.getElementById("rText").textContent = d.won
      ? d.from.name + " стал " + d.to.name + ". Шанс был " + pct(d.chance) + "."
      : d.from.name + " сгорел. Шанс был " + pct(d.chance) + ".";
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
    return HTMLResponse(BUYER_PAGE)


BUYER_PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Северо-Юг · Скупщик</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{
  --bg:#f5f3ee; --card:#fff; --ink:#1c1a17; --muted:#7c7468; --line:#e6e1d7;
  --gold:#b7791f; --gold2:#d69e2e; --soft:#fdf6e7; --ok:#0f9d58; --bad:#d93025;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg);color:var(--ink);min-height:100vh;padding-bottom:96px}
header{position:sticky;top:0;z-index:6;background:rgba(245,243,238,.94);
  backdrop-filter:blur(12px);border-bottom:1px solid var(--line);padding:15px 18px 13px}
.hrow{display:flex;align-items:center;justify-content:space-between;gap:12px}
h1{margin:0;font-size:19px;letter-spacing:-.2px}
.sub{font-size:12px;color:var(--muted);margin-top:4px}
.bal{font-weight:800;font-size:15px;background:var(--soft);color:var(--gold);
  border-radius:999px;padding:8px 14px;white-space:nowrap}
.hint{margin:10px 18px 0;background:var(--soft);border:1px solid #f0e2c2;border-radius:12px;
  padding:11px 13px;font-size:12.5px;color:#7a5c1c;line-height:1.5}
.dupes{margin:12px 18px 0}
.dupes button{width:100%;border:0;border-radius:13px;padding:15px;font-size:14.5px;font-weight:800;
  color:#fff;background:linear-gradient(135deg,var(--gold2),var(--gold))}
.dupes button[disabled]{background:#e3ded3;color:#a49b8c}
main{padding:14px 18px}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:11px}
.item{background:var(--card);border:1px solid var(--line);border-radius:15px;overflow:hidden;
  display:flex;flex-direction:column}
.item .pic{height:104px;background:#efece4;display:flex;align-items:center;justify-content:center;font-size:38px}
.item .pic img{width:100%;height:100%;object-fit:cover}
.item .body{padding:10px 11px 0}
.item .nm{font-weight:700;font-size:13px;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.item .rr{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.7px;margin-top:3px}
.item .mk{font-size:11px;color:var(--muted);margin-top:6px;text-decoration:line-through}
.item .pr{font-size:16px;font-weight:900;color:var(--gold);margin-top:1px}
.item .sell{margin:9px 10px 10px;border:0;border-radius:11px;padding:11px;font-size:13.5px;
  font-weight:800;color:#fff;background:linear-gradient(135deg,var(--gold2),var(--gold))}
.item .sell:active{transform:scale(.98)}
.item .sell[disabled]{background:#e3ded3;color:#a49b8c}
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
  const pic = it.image ? '<img src="' + it.image + '" alt="">' : it.emoji;
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
  document.getElementById("bal").textContent = money(S.balance) + " очк.";
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
