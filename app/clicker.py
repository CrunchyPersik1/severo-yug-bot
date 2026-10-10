"""Кликер: тапаешь кнопку — что-то падает. В основном очки.

Редкие награды (крутки, кейсы, карты) специально с маленьким шансом,
чтобы кликер не стал станком для фарма.
"""

from __future__ import annotations

import random

from .cards import Card
from .gacha import roll_card

POINTS = "points"
DROP = "drop"
SPIN = "spin"
CASE = "case"
CARD = "card"

# 90% тапов — очки. На крутки по 3%, на кейсы и карты по 2%.
WEIGHTS: dict[str, float] = {
    POINTS: 0.90,
    DROP: 0.03,
    SPIN: 0.03,
    CASE: 0.02,
    CARD: 0.02,
}

POINTS_MIN = 5
POINTS_MAX = 50

# Чтобы один игрок не заспамил кнопку.
TAP_COOLDOWN_SECONDS = 1.2


def roll_reward(rng: random.Random | None = None) -> tuple[str, object]:
    """Что упало: (вид, значение). Для карты значение — это Card."""
    rng = rng or random
    keys = list(WEIGHTS)
    kind = rng.choices(keys, weights=[WEIGHTS[k] for k in keys], k=1)[0]
    if kind == POINTS:
        return kind, rng.randint(POINTS_MIN, POINTS_MAX)
    if kind == CARD:
        return kind, roll_card(rng)
    return kind, 1


def label(kind: str, value: object) -> str:
    """Короткая подпись для ответа на тап."""
    if kind == POINTS:
        return f"💰 +{int(value)} очков"
    if kind == DROP:
        return "🎴 +1 крутка «Северо-Юг»!"
    if kind == SPIN:
        return "🎰 +1 спин рулетки!"
    if kind == CASE:
        return "📦 Кейс! Открывай в /case"
    card = value
    if isinstance(card, Card):
        return f"🃏 Карта: {card.name}!"
    return "🃏 Карта!"
