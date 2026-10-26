"""Кейсы: закрытый предмет, из которого выпадает карта эпической редкости и выше."""

from __future__ import annotations

import random

from .cards import CARDS_BY_RARITY, Card, rarity_name

# Рыночная цена кейса фиксирована и не зависит от того, что внутри.
CASE_PRICE = 5000

# Лимиты на открытие кейсов: иначе экономику можно обвалить за вечер.
OPEN_COOLDOWN_SECONDS = 60   # не чаще одного кейса в минуту
OPEN_PER_DAY = 15            # и не больше 15 за сутки

# Ниже эпической из кейса не выпадает ничего.
# По ТЗ ульта в 7Г — 0.25%: разницу забирает эпик, сумма остаётся 1.
CASE_RARITY_WEIGHTS: dict[str, float] = {
    "epic": 0.6075,
    "mythic": 0.28,
    "legendary": 0.08,
    "secret": 0.015,
    "ultimate": 0.015,
    "ultra": 0.0025,
}

CASE_RARITY_ORDER: tuple[str, ...] = (
    "epic", "mythic", "legendary", "secret", "ultimate", "ultra",
)


# --- кейс «Ультра» ---------------------------------------------------
# Дорогой кейс за 15 000 очков: внутри только две ультры (Садыков и Лера)
# и пустота. Шансы по ТЗ: 0.01% ульта, по 1% крутка и очки до 50 000,
# остальное — пусто.
ULTRA_CASE_PRICE = 15_000
ULTRA_CASE_IDS: tuple[str, ...] = ("daniyar_epic", "valeriya")
ULTRA_CASE_WEIGHTS: dict[str, float] = {
    "ultra": 0.0001,
    "spin": 0.01,
    "points": 0.01,
    "empty": 0.9799,
}
ULTRA_POINTS_MIN = 10_000
ULTRA_POINTS_MAX = 50_000


def ultra_case_odds() -> list[dict]:
    """Расклад для интерфейса: шанс в процентах."""
    return [
        {"key": "ultra", "title": "Ультралегендарный", "chance": 0.01,
         "note": "Садыков или Лера"},
        {"key": "spin", "title": "Крутка рулетки", "chance": 1.0, "note": "одна"},
        {"key": "points", "title": "Очки", "chance": 1.0, "note": "до 50 000"},
        {"key": "empty", "title": "Пусто", "chance": 97.99, "note": "ничего"},
    ]


def roll_ultra_case(rng: random.Random | None = None) -> dict:
    """Что выпало из кейса «Ультра»."""
    rng = rng or random
    keys = list(ULTRA_CASE_WEIGHTS)
    kind = rng.choices(keys, weights=[ULTRA_CASE_WEIGHTS[k] for k in keys], k=1)[0]
    if kind == "ultra":
        return {"kind": "ultra", "card": rng.choice(list(ULTRA_CASE_IDS))}
    if kind == "points":
        steps = list(range(ULTRA_POINTS_MIN, ULTRA_POINTS_MAX + 1, 1_000))
        return {"kind": "points", "amount": int(rng.choice(steps))}
    return {"kind": kind}


def case_rarities() -> list[str]:
    return list(CASE_RARITY_WEIGHTS)


def roll_case_rarity(rng: random.Random | None = None) -> str:
    rng = rng or random
    keys = case_rarities()
    return rng.choices(keys, weights=[CASE_RARITY_WEIGHTS[k] for k in keys], k=1)[0]


def roll_case_card(rng: random.Random | None = None) -> Card:
    rng = rng or random
    return rng.choice(CARDS_BY_RARITY[roll_case_rarity(rng)])


def case_contents() -> str:
    return "эпические и выше, вплоть до ультралегендарных (есть и ультимативные)"


# Цвета редкостей для ленты в мини-аппке.
RARITY_COLORS: dict[str, str] = {
    "epic": "#a855f7",
    "mythic": "#ef4444",
    "legendary": "#eab308",
    "secret": "#64748b",
    "ultimate": "#e879f9",
    "ultra": "#22d3ee",
    "teacher": "#a16207",
    "rare": "#94a3b8",
    "superrare": "#3b82f6",
}


def case_pool() -> list[dict]:
    """Карты, которые могут выпасть из кейса, — для ленты в мини-аппке.

    Цена считается с учётом редкости: у ультралегендарной карты она вчетверо
    выше базовых очков, и лента должна показывать именно её, а не «points».
    """
    from .market import market_price

    pool: list[dict] = []
    for rarity in CASE_RARITY_ORDER:
        for card in CARDS_BY_RARITY[rarity]:
            pool.append(
                {
                    "id": card.card_id,
                    "name": card.name,
                    "emoji": card.rarity_emoji,
                    "rarity": card.rarity,
                    "rarity_title": rarity_name(card.rarity),
                    "points": card.points,
                    "price": market_price(card),
                    "color": RARITY_COLORS.get(rarity, "#334155"),
                }
            )
    return pool


# --------------------------------------------------------------------------- #
# Кейс «7Д класс» — коллекция второго класса
# --------------------------------------------------------------------------- #

CASE_D_PRICE = 350_000
CASE_D_PRICE_VIP = 250_000
CASE_D_SOURCE = "case_d"

# Сверху редкости почти нереальны. Остаток 92.9% делим на эпик/сверхредкий/редкий.
CASE_D_WEIGHTS: dict[str, float] = {
    "mythic": 0.0500,
    "legendary": 0.0150,
    "secret": 0.0050,
    "ultra": 0.0010,
    "epic": 0.5000,
    "superrare": 0.2790,
    "rare": 0.1500,
}
CASE_D_ORDER: tuple[str, ...] = (
    "rare",
    "superrare",
    "epic",
    "mythic",
    "legendary",
    "secret",
    "ultra",
)


def roll_case_d(rng: random.Random | None = None) -> Card:
    """Карта из кейса «7Д класс». Только карты второй коллекции."""
    from .cards_d import CARDS_D_BY_RARITY

    rng = rng or random
    keys = list(CASE_D_WEIGHTS)
    weights = [CASE_D_WEIGHTS[key] for key in keys]
    rarity = rng.choices(keys, weights=weights, k=1)[0]
    return rng.choice(CARDS_D_BY_RARITY[rarity])


def case_pool_d() -> list[dict]:
    """Все карты «7Д» для ленты в мини-аппке."""
    from .cards_d import CARDS_D
    from .market import market_price

    pool: list[dict] = []
    for card in CARDS_D:
        pool.append(
            {
                "id": card.card_id,
                "name": card.name,
                "emoji": card.rarity_emoji,
                "rarity": card.rarity,
                "rarity_title": rarity_name(card.rarity),
                "points": card.points,
                "price": market_price(card),
                "color": RARITY_COLORS.get(card.rarity, "#334155"),
            }
        )
    return pool


def case_d_chances() -> list[tuple[str, float]]:
    return [(rarity_name(key), CASE_D_WEIGHTS[key] * 100) for key in reversed(CASE_D_ORDER)]
