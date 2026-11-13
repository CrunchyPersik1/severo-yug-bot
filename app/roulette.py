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

# --------------------------------------------------------------------------- #
# Виды рулеток
# --------------------------------------------------------------------------- #
#
# Рулетка — не одна. Классическая (очки, кейс, Дэниэл) и кристальная
# (кристаллы, кейсы, крупные очки). Обе крутятся по одному сбросу суток,
# у обеих есть свой счётчик спинов, и обе умеют крутить до MAX_SPINS_AT_ONCE
# за раз: сервер списывает столько спинов, сколько просят, одной транзакцией.

KIND_CLASSIC = "classic"
KIND_CRYSTAL = "crystal"
KINDS: tuple[str, ...] = (KIND_CLASSIC, KIND_CRYSTAL)
DEFAULT_KIND = KIND_CLASSIC

KIND_TITLES: dict[str, str] = {
    KIND_CLASSIC: "Классическая",
    KIND_CRYSTAL: "Кристальная",
}

# Больше трёх за раз крутить нельзя: лента превращается в кашу.
MAX_SPINS_AT_ONCE = 3

# Кристальная: один бесплатный спин в сутки, остальные — за очки.
CRYSTAL_SPINS_PER_DAY = 1
CRYSTAL_SPIN_PRICE = 25_000

# Очковые призы кристальной рулетки: (минимум, максимум, вес).
CRYSTAL_POINT_TIERS: tuple[tuple[int, int, float], ...] = (
    (1_000, 4_999, 0.50),
    (5_000, 50_000, 0.385),
)

PRIZE_CRYSTALS = "crystals"
PRIZE_CASE_G = "case_g"
PRIZE_CASE_D = "case_d"
PRIZE_CASE_ULTRA = "case_ultra"

# Полная раскладка кристальной рулетки. Сумма весов ровно 1.
CRYSTAL_WEIGHTS: dict[str, float] = {
    "crystals_10": 0.005,
    "crystals_5": 0.010,
    PRIZE_CASE_ULTRA: 0.005,
    PRIZE_CASE_D: 0.010,
    PRIZE_CASE_G: 0.085,
    "points_big": 0.385,
    "points_small": 0.500,
}

CRYSTAL_TITLES: dict[str, str] = {
    "crystals_10": "10 кристаллов",
    "crystals_5": "5 кристаллов",
    PRIZE_CASE_ULTRA: "Кейс «Ультра»",
    PRIZE_CASE_D: "Кейс «7Д класс»",
    PRIZE_CASE_G: "Кейс 7Г",
    "points_big": "Очки 5 000–50 000",
    "points_small": "Очки 1 000–5 000",
}

CRYSTAL_COLORS: dict[str, str] = {
    "crystals_10": "#22d3ee",
    "crystals_5": "#0ea5e9",
    PRIZE_CASE_ULTRA: "#b45309",
    PRIZE_CASE_D: "#7c3aed",
    PRIZE_CASE_G: "#15803d",
    "points_big": "#eab308",
    "points_small": "#1d4ed8",
}

# Сколько кристаллов даёт приз (0 — приз не про кристаллы).
CRYSTAL_AMOUNTS: dict[str, int] = {"crystals_10": 10, "crystals_5": 5}


def kind_title(kind: str | None) -> str:
    return KIND_TITLES.get(str(kind or ""), KIND_TITLES[DEFAULT_KIND])


def is_kind(kind: str | None) -> bool:
    return str(kind or "") in KINDS


def clamp_count(value: Any, low: int = 1, high: int = MAX_SPINS_AT_ONCE) -> int:
    """Сколько круток просят — в разумных пределах."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return low
    return max(low, min(high, number))


def spin_plan(free_left: int, count: int, price: int) -> tuple[int, int]:
    """Сколько спинов сверх бесплатных и во сколько они обойдутся.

    Сначала тратятся бесплатные, потом платные. Не хватило очков — вызывающая
    сторона просто откажет целиком, частичного списания не бывает.
    """
    count = max(0, int(count))
    free = max(0, min(int(free_left), count))
    paid = count - free
    return paid, paid * max(0, int(price))


def crystal_weights() -> dict[str, float]:
    return dict(CRYSTAL_WEIGHTS)


def roll_crystal_points(rng: random.Random | None = None) -> int:
    rng = rng or random
    tiers = list(CRYSTAL_POINT_TIERS)
    low, high, _ = rng.choices(tiers, weights=[t[2] for t in tiers], k=1)[0]
    return rng.randint(int(low), int(high))


def roll_crystal_prize(rng: random.Random | None = None) -> dict:
    """Приз кристальной рулетки одним словарём.

    Возвращает {"key", "kind", "amount", "label"}. kind — с чем работать
    дальше (кристаллы, кейс какого типа или очки).
    """
    rng = rng or random
    keys = list(CRYSTAL_WEIGHTS)
    key = rng.choices(keys, weights=[CRYSTAL_WEIGHTS[k] for k in keys], k=1)[0]
    if key in CRYSTAL_AMOUNTS:
        amount = CRYSTAL_AMOUNTS[key]
        return {"key": key, "kind": PRIZE_CRYSTALS, "amount": amount,
                "label": f"💎 +{amount} кристаллов!"}
    if key == PRIZE_CASE_G:
        return {"key": key, "kind": PRIZE_CASE_G, "label": "📦 Кейс 7Г!"}
    if key == PRIZE_CASE_D:
        return {"key": key, "kind": PRIZE_CASE_D, "label": "📦 Кейс «7Д класс»!"}
    if key == PRIZE_CASE_ULTRA:
        return {"key": key, "kind": PRIZE_CASE_ULTRA, "label": "🎟 Кейс «Ультра»!"}
    amount = roll_crystal_points(rng)
    return {"key": key, "kind": PRIZE_POINTS, "amount": amount,
            "label": f"💰 +{amount} очков!"}


def crystal_segments() -> list[dict]:
    """Сегменты кристального колеса — доли совпадают с реальными шансами."""
    segments: list[dict] = []
    for key in CRYSTAL_WEIGHTS:
        segments.append(
            {
                "key": key,
                "label": CRYSTAL_TITLES[key],
                "color": CRYSTAL_COLORS[key],
                "weight": CRYSTAL_WEIGHTS[key],
            }
        )
    return segments


def crystal_segment_index(key: str) -> int:
    keys = list(CRYSTAL_WEIGHTS)
    return keys.index(key) if key in keys else 0


def kind_segments(kind: str | None) -> list[dict]:
    """Сегменты колеса для вида рулетки."""
    if str(kind or "") == KIND_CRYSTAL:
        return crystal_segments()
    return wheel_segments()
