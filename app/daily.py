"""Ежедневная награда за заход в магазин.

Одна награда в игровые сутки (сброс в 12:00 по ЕКБ, как у карт), серия
подряд даёт множитель. Джекпот — отдельный редкий исход, а не «чуть больше
очков»: он должен быть событием.
"""

from __future__ import annotations

import random
from typing import Any

from . import bundles
from .cards import CARDS_BY_RARITY

# Множитель за серию: 7 дней подряд — полторы награды.
STREAK_TARGET = 7
STREAK_BONUS = 1.5

TIER_POINTS = "points"
TIER_YUGI = "yugi"
TIER_GEMS = "gems"
TIER_CASE = "case"
TIER_SPIN = "spin"
TIER_CARD = "card"
TIER_JACKPOT = "jackpot"

# Шансы договорены: обычные очки/юги основа, кейсы и карты — редкость.
WEIGHTS: dict[str, float] = {
    TIER_POINTS: 55.0,
    TIER_YUGI: 20.0,
    TIER_GEMS: 15.0,
    TIER_CASE: 5.0,
    TIER_SPIN: 3.0,
    TIER_CARD: 1.5,
    TIER_JACKPOT: 0.5,
}

JACKPOTS: tuple[dict[str, Any], ...] = (
    {"title": "ДЖЕКПОТ · 150 000 очков", "bundle": {"points": 150_000}},
    {"title": "ДЖЕКПОТ · 15 кристаллов", "bundle": {"gems": 15}},
    {"title": "ДЖЕКПОТ · 1 000 000 Югов", "bundle": {"yugi": 1_000_000}},
)


def tiers() -> list[str]:
    return list(WEIGHTS)


def roll(rng: random.Random | None = None) -> dict[str, Any]:
    """Что выпало сегодня: готовая награда и её название."""
    rng = rng or random
    kind = rng.choices(tiers(), weights=[WEIGHTS[k] for k in tiers()], k=1)[0]
    if kind == TIER_POINTS:
        amount = rng.choice([50, 100, 250, 500, 1000, 2500, 5000, 10_000, 15_000])
        return {"tier": kind, "title": f"{amount:,}".replace(",", " ") + " очков",
                "bundle": {"points": amount}}
    if kind == TIER_YUGI:
        amount = rng.choice([10_000, 25_000, 50_000, 75_000, 100_000])
        return {"tier": kind, "title": f"{amount:,}".replace(",", " ") + " Югов",
                "bundle": {"yugi": amount}}
    if kind == TIER_GEMS:
        amount = rng.randint(1, 5)
        word = bundles.plural(amount, "кристалл", "кристалла", "кристаллов")
        return {"tier": kind, "title": f"{amount} {word}", "bundle": {"gems": amount}}
    if kind == TIER_CASE:
        return {"tier": kind, "title": "кейс 7Г", "bundle": {"cases_g": 1}}
    if kind == TIER_SPIN:
        return {"tier": kind, "title": "крутка рулетки", "bundle": {"spins": 1}}
    if kind == TIER_CARD:
        pool = CARDS_BY_RARITY["epic"] + CARDS_BY_RARITY["mythic"]
        card = rng.choice(pool)
        return {"tier": kind, "title": "карта: " + card.display_name,
                "bundle": {"cards": [card.card_id]}}
    jackpot = rng.choice(list(JACKPOTS))
    return {"tier": TIER_JACKPOT, "title": jackpot["title"], "bundle": dict(jackpot["bundle"])}


def streak_multiplier(streak: int) -> float:
    """Серия от 7 дней подряд умножает награду (кроме джекпота)."""
    return STREAK_BONUS if int(streak) >= STREAK_TARGET else 1.0


def apply_multiplier(prize: dict[str, Any], multiplier: float) -> dict[str, Any]:
    """Умножает числовые награды, не трогая кейсы, крутки и карты."""
    if multiplier <= 1.0 or prize.get("tier") == TIER_JACKPOT:
        return prize
    bundle = dict(prize.get("bundle") or {})
    scaled: dict[str, Any] = {}
    for key, value in bundle.items():
        # Множим только «сыпучие» награды: кейсы, крутки и карты штучные.
        if key in ("points", "gems", "yugi") and isinstance(value, int):
            scaled[key] = int(round(value * multiplier))
        else:
            scaled[key] = value
    out = dict(prize)
    out["bundle"] = scaled
    out["title"] = prize["title"] + f" ×{multiplier:g}"
    return out
