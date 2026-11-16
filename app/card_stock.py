"""Общий сток карт в магазине: обновляется каждые 5 минут.

Ассортимент одинаковый для всех игроков — он считается от номера окна
времени, а не от базы. Покупка индивидуальна: взяв карту, ты не забираешь
её из стока у других.
"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from . import cards as cards_mod
from . import cards_d as cards_d_mod

WINDOW_SECONDS = 300          # окно стока: 5 минут
SLOTS = 8                     # сколько карт в витрине
GEM_RARITIES = {"ultimate", "ultra", "teacher", "secret"}

# Базовая цена по редкости, в очках. Редкие карты идут за гемы.
POINTS_PRICE = {
    "rare": 45_000,
    "superrare": 90_000,
    "epic": 180_000,
    "mythic": 320_000,
    "legendary": 520_000,
    "secret": 800_000,
    "ultimate": 1_200_000,
    "ultra": 2_000_000,
    "teacher": 600_000,
}
GEM_PRICE = {
    "secret": 90,
    "ultimate": 140,
    "ultra": 220,
    "teacher": 70,
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def window_key(moment: datetime | None = None) -> int:
    moment = moment or now()
    return int(moment.timestamp()) // WINDOW_SECONDS


def seconds_left(moment: datetime | None = None) -> int:
    moment = moment or now()
    return WINDOW_SECONDS - int(moment.timestamp()) % WINDOW_SECONDS


def _pool() -> list[tuple[str, str, int]]:
    """Все карты обеих коллекций: (id, редкость, очки карты)."""
    out = []
    for card in list(cards_mod.CARDS) + list(cards_d_mod.CARDS_D):
        out.append((card.card_id, card.rarity, int(getattr(card, "points", 0) or 0)))
    return out


def _weight(rarity: str) -> float:
    """Чем реже редкость, тем меньше шанс попасть в сток."""
    base = cards_mod.RARITIES.get(rarity)
    weight = float(getattr(base, "weight", 0.05) or 0.05)
    return max(0.05, weight)


def stock(window: int | None = None) -> list[dict[str, Any]]:
    window = window_key() if window is None else int(window)
    seed = int(hashlib.sha256(f"cardstock:{window}".encode()).hexdigest()[:12], 16)
    rng = random.Random(seed)
    pool = _pool()
    rarities = [item[1] for item in pool]
    weights = [_weight(rarity) for rarity in rarities]
    picked: list[dict[str, Any]] = []
    used: set[str] = set()
    guard = 0
    while len(picked) < SLOTS and guard < 400:
        guard += 1
        card_id, rarity, points = rng.choices(pool, weights=weights, k=1)[0]
        if card_id in used:
            continue
        used.add(card_id)
        currency = "gems" if rarity in GEM_RARITIES else "points"
        price = GEM_PRICE.get(rarity) if currency == "gems" else POINTS_PRICE.get(rarity)
        if price is None:
            price = max(10_000, points * 6)
        picked.append(
            {
                "id": card_id,
                "rarity": rarity,
                "currency": currency,
                "price": int(price),
                "collection": "d" if card_id in cards_d_mod.CARDS_D_BY_ID else "main",
            }
        )
    return picked


def find(card_id: str, window: int | None = None) -> dict[str, Any] | None:
    for item in stock(window):
        if item["id"] == card_id:
            return item
    return None


def payload(owned: set[str] | None = None, window: int | None = None) -> dict[str, Any]:
    window = window_key() if window is None else int(window)
    owned = owned or set()
    items = stock(window)
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
        "stock": items,
    }
