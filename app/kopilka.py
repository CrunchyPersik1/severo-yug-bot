"""Копилка — отдельный кликер ивента.

От обычного кликера (/admin clicker) отличается главным: награды НЕ
выдаются сразу. Всё падает в копилку и раздаётся разом, когда админ
выключит ивент командой /admin event.

Старый кликер это не трогает — он живёт своей жизнью.
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

KINDS = (POINTS, DROP, SPIN, CASE, CARD)

# Обычный кликер: почти всё — очки, редкое — приятный бонус.
WEIGHTS: dict[str, float] = {
    POINTS: 0.900,
    DROP: 0.050,
    SPIN: 0.030,
    CASE: 0.015,
    CARD: 0.005,
}

POINTS_MIN = 5
POINTS_MAX = 60

# Чтобы кнопку не заспамили в ноль.
TAP_COOLDOWN_SECONDS = 0.8


def roll(rng: random.Random | None = None) -> tuple[str, object]:
    """Что упало в копилку: (вид, значение)."""
    rng = rng or random
    keys = list(WEIGHTS)
    kind = rng.choices(keys, weights=[WEIGHTS[k] for k in keys], k=1)[0]
    if kind == POINTS:
        return kind, rng.randint(POINTS_MIN, POINTS_MAX)
    if kind == CARD:
        return kind, roll_card(rng)
    return kind, 1


def label(kind: str, value: object) -> str:
    if kind == POINTS:
        return f"💰 +{int(value)} очков"
    if kind == DROP:
        return "🎴 +1 крутка «Северо-Юг»"
    if kind == SPIN:
        return "🎰 +1 спин рулетки"
    if kind == CASE:
        return "📦 +1 кейс"
    card = value
    if isinstance(card, Card):
        return f"🃏 {card.rarity_emoji} {card.display_name}"
    return "🃏 карта"


def summary(row: dict) -> str:
    """Строка «что накопилось» — для HUD и для админского отчёта."""
    parts = [f"💰 {int(row.get('points', 0))} очк."]
    if int(row.get("drops", 0)):
        parts.append(f"🎴 ×{int(row['drops'])}")
    if int(row.get("spins", 0)):
        parts.append(f"🎰 ×{int(row['spins'])}")
    if int(row.get("cases", 0)):
        parts.append(f"📦 ×{int(row['cases'])}")
    cards = row.get("cards") or []
    if cards:
        parts.append(f"🃏 ×{len(cards)}")
    return " · ".join(parts)
