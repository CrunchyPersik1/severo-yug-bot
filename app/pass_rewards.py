
"""Награды Северо-Пасса: три дорожки на 50 уровней.

фри  — только валюта и кейсы 7Г: карты, стили, акции и аксессуары не даём
сп+  — полная дорожка: карты, стили, акции, кейсы 7Д, кружки, VIP
сп++ — дополнительная дорожка только на уровнях 1-10 и 41-50
"""

from __future__ import annotations

import hashlib
import random
from typing import Any

from . import bundles
from .cards import CARDS, CARDS_BY_RARITY

GEM_STEPS = (5, 7, 9, 12, 15, 20, 25, 30)
PREMIUM_LEVELS = tuple(range(1, 11)) + tuple(range(41, 51))
CARD_POOL = tuple(
    card.card_id
    for card in CARDS
    if card.rarity in ("epic", "mythic", "legendary", "secret", "ultimate")
)
STYLE_POOL = ("astra", "violet", "green", "acid", "electric", "blood", "rust", "graphite")


def _rng(season: str, salt: str) -> random.Random:
    digest = hashlib.sha256(f"passrw|{season}|{salt}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def _free(level: int, rng: random.Random) -> dict[str, Any]:
    """Фри-дорожка: только валюта и кейсы 7Г."""
    if level % 10 == 0:
        return bundles.make(points=2500 + level * 120, cases_g=2)
    if level % 5 == 0:
        return bundles.make(gems=GEM_STEPS[level // 8 % len(GEM_STEPS)], cases_g=1)
    if level % 2 == 0:
        return bundles.make(cases_g=1)
    return bundles.make(points=300 + level * 80)


def _plus(level: int, rng: random.Random) -> dict[str, Any]:
    """Дорожка сп+: карты, стили, акции, кейсы 7Д."""
    parts: dict[str, Any] = {"points": 500 + level * 150}
    if level % 10 == 0:
        parts.update(cards=[rng.choice(CARD_POOL)], cases_d=2, gems=25)
    elif level % 5 == 0:
        parts.update(cases_d=1, gems=12, shares=rng.choice((10, 15, 25)))
    elif level % 3 == 0:
        parts.update(cards=[rng.choice(CARD_POOL)])
    elif level % 2 == 0:
        parts.update(cases_g=2)
    if level == 25:
        parts.update(cards=[rng.choice(CARD_POOL)], vip_days=3)
    return bundles.make(**parts)


def _premium(level: int, rng: random.Random) -> dict[str, Any] | None:
    """Дорожка сп++: только 1-10 и 41-50."""
    if level not in PREMIUM_LEVELS:
        return None
    parts: dict[str, Any] = {"points": 1500 + level * 200, "gems": 10 + level // 5}
    if level % 10 == 0 or level == 50:
        parts.update(cases_ultra=1, cases_d=1)
    elif level % 5 == 0:
        parts.update(cases_d=1)
    return bundles.make(**parts)


def levels(season: str) -> list[dict[str, Any]]:
    """Все 50 уровней: награды фри, сп+ и сп++."""
    out: list[dict[str, Any]] = []
    for level in range(1, 51):
        rng = _rng(season, str(level))
        out.append(
            {
                "level": level,
                "free": _free(level, rng),
                "plus": _plus(level, rng),
                "premium": _premium(level, rng),
            }
        )
    return out


def level(season: str, number: int) -> dict[str, Any] | None:
    for row in levels(season):
        if row["level"] == int(number):
            return row
    return None


# --- Бонусные награды после 50 уровня ------------------------------------ #

def bonus_choices(season: str, step: int) -> list[dict[str, Any]]:
    """Два варианта за каждые 2800 очков: первый бесплатный, второй за гемы."""
    rng = _rng(season, f"bonus{step}")
    card = rng.choice(CARD_POOL)
    free = bundles.make(
        cases_g=rng.choice((2, 3)),
        points=rng.choice((3000, 5000)),
    )
    good = bundles.make(
        cards=[card],
        gems=rng.choice((15, 20)),
    )
    price = int(
        min(
            79,
            max(19, 19 + round(bundles.value(good) / 90_000 * 60)),
        )
    )
    return [
        {"index": 1, "bundle": free, "gems": 0},
        {"index": 2, "bundle": good, "gems": price},
    ]
