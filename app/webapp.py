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
from . import themes
from . import cases as cases_mod
from . import roulette as roulette_mod
from . import upgrader
from .cards import (
    CARDS,
    CARDS_BY_ID,
    cards_sorted_for_user,
    get_card,
    image_url,
    rarity_name,
)
from .cases import roll_case_card
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
const TABS = [["card","Учителя"],["pack","Наборы"],["accessory","Аксессуары"],["theme","Стили"]];

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
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{
  --bg:#12100e; --panel:#1b1815; --panel2:#231f1a; --line:#332d26;
  --ink:#f2ece5; --muted:#9c9086; --acc:#dc8a3f; --acc2:#f0b276; --acc-ink:#1b1206;
  --up:#9dc941; --down:#e0407a;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0;overscroll-behavior:none}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg);color:var(--ink);min-height:100vh;padding-bottom:26px}
.top{display:flex;align-items:center;gap:10px;padding:13px 15px;border-bottom:1px solid var(--line);
  position:sticky;top:0;z-index:9;background:color-mix(in srgb,var(--bg) 90%,transparent);backdrop-filter:blur(12px)}
.back{background:var(--panel);border:1px solid var(--line);border-radius:999px;color:var(--ink);
  padding:9px 16px;font-size:14px;font-weight:700}
.top .ttl{flex:1;text-align:center;font-size:15px;font-weight:800;letter-spacing:.3px}
.top .sp{width:70px}

.hero{padding:16px 15px 8px}
.hero .nm{font-size:26px;font-weight:900;letter-spacing:-.6px;line-height:1.1}
.hero .sub{font-size:12px;color:var(--muted);margin-top:3px}
.hero .pr{font-size:34px;font-weight:900;letter-spacing:-1.2px;margin-top:12px}
.hero .ch{font-size:15px;font-weight:800;margin-top:2px}
.up{color:var(--up)} .down{color:var(--down)}

.stats{display:grid;grid-template-columns:1fr 1fr;gap:9px;padding:12px 15px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.stat span{display:block;font-size:10.5px;letter-spacing:.9px;text-transform:uppercase;color:var(--muted);font-weight:700}
.stat b{display:block;font-size:16px;font-weight:900;margin-top:4px}

.bar{display:flex;gap:7px;padding:4px 15px 10px;overflow-x:auto;scrollbar-width:none}
.bar::-webkit-scrollbar{display:none}
.tf{flex:0 0 auto;border:1px solid var(--line);background:transparent;color:var(--muted);
  border-radius:9px;padding:8px 13px;font-size:12.5px;font-weight:800}
.tf.on{background:var(--panel2);color:var(--ink);border-color:var(--muted)}

.chart{padding:0 15px}
.chartbox{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:10px 6px 6px;
  position:relative;overflow:hidden}
svg{display:block;width:100%;height:230px}
.axis{position:absolute;right:8px;top:10px;bottom:10px;display:flex;flex-direction:column;
  justify-content:space-between;font-size:10px;color:var(--muted);pointer-events:none}
.note{padding:9px 15px 0;font-size:11.5px;color:var(--muted)}

.act{display:flex;gap:9px;padding:14px 15px 0}
.act button{flex:1;border:0;border-radius:13px;padding:15px;font-size:15px;font-weight:900;letter-spacing:.3px}
.buy{background:var(--acc);color:var(--acc-ink)}
.sell{background:var(--panel2);color:var(--ink);border:1px solid var(--line)!important}
.act button[disabled]{opacity:.45}
.stepper{display:flex;gap:7px;padding:11px 15px 0;flex-wrap:wrap}
.stepper button{border:1px solid var(--line);background:transparent;color:var(--muted);
  border-radius:10px;padding:9px 14px;font-size:13px;font-weight:800}
.stepper button.on{background:var(--acc);color:var(--acc-ink);border-color:transparent}

.list{padding:16px 15px 0}
.lhead{font-size:11px;letter-spacing:1.3px;text-transform:uppercase;color:var(--muted);font-weight:800;
  padding:0 2px 9px}
.row{display:flex;align-items:center;gap:12px;background:var(--panel);border:1px solid var(--line);
  border-radius:13px;padding:12px 13px;margin-bottom:8px}
.row.on{border-color:var(--acc)}
.row .av{width:38px;height:38px;border-radius:50%;border:1px solid var(--line);flex:0 0 auto;
  display:flex;align-items:center;justify-content:center;font-size:17px;background:var(--panel2)}
.row .mid{flex:1;min-width:0}
.row .nm{font-size:14.5px;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row .mt{font-size:11px;color:var(--muted);margin-top:2px}
.row .rt{text-align:right}
.row .rt b{display:block;font-size:14.5px;font-weight:900}
.row .rt i{display:block;font-style:normal;font-size:11.5px;font-weight:800;margin-top:2px}
#toast{position:fixed;left:14px;right:14px;bottom:16px;background:var(--panel2);color:var(--ink);
  border:1px solid var(--line);border-radius:12px;padding:13px 15px;font-size:13px;
  transform:translateY(220%);transition:.25s;z-index:30}
#toast.on{transform:translateY(0)}
</style>
</head>
<body>
<div class="top">
  <button class="back" onclick="location.href='/hub'">‹ Назад</button>
  <div class="ttl">Биржа</div>
  <div class="sp"></div>
</div>

<div class="hero">
  <div class="nm" id="nm">…</div>
  <div class="sub" id="sub">акция · курс обновляется каждый час</div>
  <div class="pr" id="pr">…</div>
  <div class="ch" id="ch"></div>
</div>

<div class="stats">
  <div class="stat"><span>Покупка</span><b id="stBuy">…</b></div>
  <div class="stat"><span>Продажа</span><b id="stSell">…</b></div>
  <div class="stat"><span>У тебя акций</span><b id="stShares">…</b></div>
  <div class="stat"><span>Твоя прибыль</span><b id="stPnl">…</b></div>
</div>

<div class="bar" id="tfBar"></div>

<div class="chart">
  <div class="chartbox">
    <svg id="cv" viewBox="0 0 320 230" preserveAspectRatio="none"></svg>
    <div class="axis" id="axis"></div>
  </div>
  <div class="note" id="note"></div>
</div>

<div class="stepper" id="stepBar"></div>
<div class="act">
  <button class="buy" id="buyBtn">Купить</button>
  <button class="sell" id="sellBtn">Продать</button>
</div>

<div class="list">
  <div class="lhead">Все акции</div>
  <div id="rows"></div>
</div>

<div id="toast"></div>
<script>
const tg = window.Telegram ? window.Telegram.WebApp : null;
const headers = {"X-Telegram-Init-Data": tg ? tg.initData : "", "Content-Type": "application/json"};
const TFS = [["1м", 60], ["5м", 44], ["15м", 30], ["1ч", 18]];
let S = {data: null, slug: null, tf: 0, shares: 1, busy: false};

function esc(s){ return String(s).replace(/[<>&]/g, c => ({"<":"&lt;",">":"&gt;","&":"&amp;"}[c])); }
function money(n){ return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, " "); }
function toast(t){
  const el = document.getElementById("toast");
  el.textContent = t; el.className = "on";
  clearTimeout(el._t); el._t = setTimeout(() => el.className = "", 3000);
}
function cur(){ return S.data.stocks.find(s => s.slug === S.slug); }

// Свечи: бьём историю на N кусков и считаем OHLC каждого
function candles(history, count){
  const out = [];
  const size = Math.max(1, Math.floor(history.length / count));
  for (let i = 0; i < history.length; i += size){
    const chunk = history.slice(i, i + size);
    if (!chunk.length) continue;
    out.push({o: chunk[0], c: chunk[chunk.length - 1], h: Math.max.apply(null, chunk), l: Math.min.apply(null, chunk)});
  }
  return out;
}
function draw(){
  const s = cur();
  if (!s) return;
  const bars = candles(s.history, TFS[S.tf][1]);
  const hi = Math.max.apply(null, bars.map(b => b.h));
  const lo = Math.min.apply(null, bars.map(b => b.l));
  const pad = (hi - lo) * 0.12 || 1;
  const top = hi + pad, bot = lo - pad;
  const n = bars.length, w = 320 / n, bw = Math.max(3, w * 0.62);
  const y = v => 8 + (1 - (v - bot) / (top - bot)) * 214;
  let svg = "";
  // сетка
  for (let g = 0; g <= 4; g++){
    const gy = 8 + g * 53.5;
    svg += '<line x1="0" y1="' + gy + '" x2="320" y2="' + gy + '" stroke="var(--line)" stroke-width="0.5"/>';
  }
  bars.forEach((b, i) => {
    const x = i * w + w / 2;
    const up = b.c >= b.o;
    const col = up ? "var(--up)" : "var(--down)";
    svg += '<line x1="' + x + '" y1="' + y(b.h) + '" x2="' + x + '" y2="' + y(b.l) +
           '" stroke="' + col + '" stroke-width="1"/>';
    const y1 = Math.min(y(b.o), y(b.c)), y2 = Math.max(y(b.o), y(b.c));
    svg += '<rect x="' + (x - bw / 2) + '" y="' + y1 + '" width="' + bw + '" height="' +
           Math.max(1.6, y2 - y1) + '" fill="' + col + '" rx="1"/>';
  });
  const last = bars[bars.length - 1];
  svg += '<line x1="0" y1="' + y(last.c) + '" x2="320" y2="' + y(last.c) +
         '" stroke="var(--acc)" stroke-width="0.7" stroke-dasharray="3 3"/>';
  document.getElementById("cv").innerHTML = svg;
  const a = document.getElementById("axis");
  a.innerHTML = [top, (top + bot) / 2, bot].map(v => "<span>" + money(v) + "</span>").join("");
}
function paint(){
  const s = cur();
  if (!s){ return; }
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
function renderTf(){
  document.getElementById("tfBar").innerHTML = TFS.map((t, i) =>
    '<button class="tf' + (i === S.tf ? " on" : "") + '" data-tf="' + i + '">' + t[0] + '</button>').join("");
  document.querySelectorAll("[data-tf]").forEach(b => b.onclick = () => {
    S.tf = +b.dataset.tf; renderTf(); draw();
  });
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
      toast((kind === "buy" ? "Куплено " : "Продано ") + S.shares + " акц.");
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
renderTf(); renderStep();
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
    {"id": "collection", "title": "Коллекция", "note": "все твои карты", "kind": "panel"},
    {"id": "market", "title": "Рынок", "note": "лоты игроков", "kind": "app", "path": "/market"},
    {"id": "shop", "title": "Магазин", "note": "учителя и наборы", "kind": "app", "path": "/app"},
    {"id": "buyer", "title": "Скупщик", "note": "продать сразу", "kind": "app", "path": "/buyer"},
    {"id": "upgrader", "title": "Апгрейдер", "note": "обмен карт", "kind": "app", "path": "/upgrader"},
    {"id": "cases", "title": "Кейсы", "note": "открыть кейс", "kind": "app", "path": "/case_app"},
    {"id": "roulette", "title": "Рулетка", "note": "крутить колесо", "kind": "app", "path": "/roulette_app"},
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
                "level": int(profile.get("level") or 1),
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
                for section in HUB_SECTIONS
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
.mk-top{display:flex;align-items:center;justify-content:space-between;gap:12px}
.mk-side{display:flex;flex-direction:column;gap:2px;min-width:74px}
.mk-side:last-child{align-items:flex-end;text-align:right}
.mk-side b{font-size:22px;font-weight:900;letter-spacing:-.5px;line-height:1}
.mk-side span{font-size:10px;letter-spacing:1.1px;text-transform:uppercase;color:var(--muted);font-weight:700}
.mk-name{flex:1;text-align:center;font-size:21px;font-weight:900;letter-spacing:-.3px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mk-rate{text-align:center;font-size:19px;font-weight:900;letter-spacing:.2px;color:#7fd0a0}
.mk-rate.down{color:#e28d92}
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
      return '<div class="line"><div class="pos">' + (i + 1) + '</div><div class="nm">' + name +
        '</div><div class="vl">' + value + '</div></div>';
    }).join("") : '<div class="empty">Пока пусто</div>';
    show(id === "top" ? "p-top" : "p-levels");
  } else if (id === "profile"){
    const m = S.data.me;
    document.getElementById("profList").innerHTML =
      [["Имя", esc(m.name)], ["Баланс", money(m.balance) + " очк."], ["Уровень", m.level],
       ["Опыт", m.xp + " xp"], ["Побед", m.wins], ["Карт", m.cards]]
      .map(([k, v]) => '<div class="line"><div class="nm">' + k + '</div><div class="vl">' + v + '</div></div>').join("");
    show("p-profile");
  } else if (id === "style"){
    renderThemes();
    show("p-style");
  }
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
    document.getElementById("bal").textContent = money(d.me.balance);
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
