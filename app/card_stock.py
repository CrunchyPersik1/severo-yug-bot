"""Общий сток карт в магазине: обновляется каждые 5 минут.

Ассортимент считается от номера окна времени, поэтому он одинаковый у всех.
Отдельно есть платная перекрутка (19 💎) — она меняет сток только этому
игроку и не сдвигает общий таймер.
"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from . import cards as cards_mod
from . import cards_d as cards_d_mod

WINDOW_SECONDS = 300          # окно стока: 5 минут, ровно по часам
SLOTS = 8
REROLL_PRICE = 19             # 💎 за личную перекрутку

# Цена в гемах по редкости: от 1 за редкую до 80 за ультралегендарную.
# Цена в очках: дешевле редкость — дешевле карта.
POINTS_PRICE = {
    "rare": 1_000,
    "superrare": 3_000,
    "epic": 8_000,
    "mythic": 20_000,
    "legendary": 50_000,
    "secret": 100_000,
    "ultimate": 200_000,
    "ultra": 350_000,
    "teacher": 500_000,
}

GEM_PRICE = {
    "rare": 1,
    "superrare": 2,
    "epic": 5,
    "mythic": 10,
    "legendary": 15,
    "secret": 20,
    "ultimate": 40,
    "teacher": 60,
    "ultra": 80,
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def window_key(moment: datetime | None = None) -> int:
    moment = moment or now()
    return int(moment.timestamp()) // WINDOW_SECONDS


def seconds_left(moment: datetime | None = None) -> int:
    """Сколько до ровной границы окна: 16:00, 16:05, 16:10 и так далее."""
    moment = moment or now()
    return WINDOW_SECONDS - int(moment.timestamp()) % WINDOW_SECONDS


def _pool() -> list[tuple[str, str, int]]:
    out = []
    for card in list(cards_mod.CARDS) + list(cards_d_mod.CARDS_D):
        out.append((card.card_id, card.rarity, int(getattr(card, "points", 0) or 0)))
    return out


def _weight(rarity: str) -> float:
    """Чем реже редкость, тем меньше шанс попасть в сток."""
    base = cards_mod.RARITIES.get(rarity)
    weight = float(getattr(base, "weight", 0.05) or 0.05)
    return max(0.05, weight)


def stock(window: int | None = None, reroll: int = 0, user_id: int = 0) -> list[dict[str, Any]]:
    window = window_key() if window is None else int(window)
    seed_text = f"cardstock:{window}"
    if reroll or user_id:
        # личная перекрутка: свой набор, общий таймер не трогаем
        seed_text += f":{int(user_id)}:{int(reroll)}"
    seed = int(hashlib.sha256(seed_text.encode()).hexdigest()[:12], 16)
    rng = random.Random(seed)
    pool = _pool()
    weights = [_weight(rarity) for _, rarity, _ in pool]
    picked: list[dict[str, Any]] = []
    used: set[str] = set()
    guard = 0
    while len(picked) < SLOTS and guard < 400:
        guard += 1
        card_id, rarity, points = rng.choices(pool, weights=weights, k=1)[0]
        if card_id in used:
            continue
        used.add(card_id)
        gems = GEM_PRICE.get(rarity)
        if gems is None:
            gems = max(1, points // 1000)
        cost = POINTS_PRICE.get(rarity)
        if cost is None:
            cost = max(1_000, points * 3)
        picked.append(
            {
                "id": card_id,
                "rarity": rarity,
                "prices": {"gems": int(gems), "points": int(cost)},
                "collection": "d" if card_id in cards_d_mod.CARDS_D_BY_ID else "main",
            }
        )
    return picked


def find(card_id: str, window: int | None = None) -> dict[str, Any] | None:
    for item in stock(window):
        if item["id"] == card_id:
            return item
    return None


def payload(
    owned: set[str] | None = None,
    window: int | None = None,
    reroll: int = 0,
    user_id: int = 0,
) -> dict[str, Any]:
    window = window_key() if window is None else int(window)
    owned = owned or set()
    items = stock(window, reroll, user_id)
    for item in items:
        item["owned"] = item["id"] in owned
        card = cards_mod.CARDS_BY_ID.get(item["id"]) or cards_d_mod.CARDS_D_BY_ID.get(item["id"])
        if card is not None:
            item["name"] = card.name
            item["emoji"] = getattr(card, "emoji", "") or ""
            item["image"] = getattr(card, "image", "") or ""
    return {
        "window": window,
        "seconds_left": seconds_left(),
        "reroll_price": REROLL_PRICE,
        "rerolls": int(reroll),
        "stock": items,
    }
