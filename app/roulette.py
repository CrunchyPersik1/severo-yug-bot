"""Ежедневная рулетка: раз в сутки в 20:00 по ЕКБ (15:00 UTC).

Призы: очки, кейс или главный приз — карта Даниэль.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

ROULETTE_RESET_HOUR_UTC = 15  # 20:00 по ЕКБ (UTC+5)

# Сколько спинов в сутки по умолчанию.
SPINS_PER_DAY = 1

PRIZE_POINTS = "points"
PRIZE_CASE = "case"
PRIZE_CARD = "card"

# Кейсы даются тяжело, главный приз — совсем редко.
PRIZE_WEIGHTS: dict[str, float] = {
    PRIZE_POINTS: 0.89,
    PRIZE_CASE: 0.10,
    PRIZE_CARD: 0.01,
}

# Главный приз рулетки — ровно одна карта.
MAIN_CARD_ID = "daniel"

# Очковый приз: (минимум, максимум, вес)
POINT_TIERS: tuple[tuple[int, int, float], ...] = (
    (100, 500, 0.50),
    (501, 1000, 0.30),
    (1001, 2500, 0.15),
    (2501, 5000, 0.05),
)


def roulette_day_key(moment: datetime | None = None) -> date:
    """Игровые сутки рулетки начинаются в 15:00 UTC."""
    moment = moment or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (moment.astimezone(timezone.utc) - timedelta(hours=ROULETTE_RESET_HOUR_UTC)).date()


def next_roulette_reset(moment: datetime | None = None) -> datetime:
    moment = moment or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    candidate = moment.replace(
        hour=ROULETTE_RESET_HOUR_UTC, minute=0, second=0, microsecond=0
    )
    if candidate <= moment:
        candidate += timedelta(days=1)
    return candidate


def prize_weights(boost: float = 1.0) -> dict[str, float]:
    """Веса призов. boost > 1 поднимает кейс и карту, очки придавливает."""
    weights = dict(PRIZE_WEIGHTS)
    if boost <= 1.0:
        return weights
    weights[PRIZE_CASE] *= boost
    weights[PRIZE_CARD] *= boost
    total = sum(weights.values())
    return {key: value / total for key, value in weights.items()}


def roll_prize_kind(rng: random.Random | None = None, boost: float = 1.0) -> str:
    rng = rng or random
    weights = prize_weights(boost)
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys], k=1)[0]


def roll_points(rng: random.Random | None = None) -> int:
    rng = rng or random
    tiers = list(POINT_TIERS)
    low, high, _ = rng.choices(tiers, weights=[t[2] for t in tiers], k=1)[0]
    return rng.randint(low, high)


def wheel_segments() -> list[dict]:
    """Сегменты колеса: их доли совпадают с реальными шансами призов."""
    colors = ("#1d4ed8", "#2563eb", "#0ea5e9", "#7c3aed")
    segments: list[dict] = []
    for index, (low, high, weight) in enumerate(POINT_TIERS):
        segments.append(
            {
                "key": f"points_{index}",
                "label": f"{low}-{high}",
                "color": colors[index % len(colors)],
                "weight": PRIZE_WEIGHTS[PRIZE_POINTS] * weight,
            }
        )
    segments.append(
        {
            "key": PRIZE_CASE,
            "label": "Кейс",
            "color": "#15803d",
            "weight": PRIZE_WEIGHTS[PRIZE_CASE],
        }
    )
    segments.append(
        {
            "key": PRIZE_CARD,
            "label": "Дэниэл",
            "color": "#b45309",
            "weight": PRIZE_WEIGHTS[PRIZE_CARD],
        }
    )
    return segments


def segment_index(prize: tuple[str, int | str]) -> int:
    """В какой сегмент колеса попадёт приз."""
    kind, value = prize
    if kind == PRIZE_POINTS:
        for index, (low, high, _) in enumerate(POINT_TIERS):
            if int(low) <= int(value) <= int(high):
                return index
        return len(POINT_TIERS) - 1
    if kind == PRIZE_CASE:
        return len(POINT_TIERS)
    return len(POINT_TIERS) + 1


def roll_prize(rng: random.Random | None = None) -> tuple[str, int | str]:
    """Возвращает ('points', 750) | ('case', 'case') | ('card', 'daniel')."""
    kind = roll_prize_kind(rng)
    if kind == PRIZE_POINTS:
        return kind, roll_points(rng)
    if kind == PRIZE_CASE:
        return kind, "case"
    return kind, MAIN_CARD_ID
