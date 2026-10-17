"""Кейсы: закрытый предмет, из которого выпадает карта эпической редкости и выше."""

from __future__ import annotations

import random

from .cards import CARDS_BY_RARITY, Card, rarity_name

# Рыночная цена кейса фиксирована и не зависит от того, что внутри.
CASE_PRICE = 5000

# Ниже эпической из кейса не выпадает ничего.
CASE_RARITY_WEIGHTS: dict[str, float] = {
    "epic": 0.60,
    "mythic": 0.28,
    "legendary": 0.08,
    "secret": 0.015,
    "ultimate": 0.015,
    "ultra": 0.01,
}

CASE_RARITY_ORDER: tuple[str, ...] = (
    "epic", "mythic", "legendary", "secret", "ultimate", "ultra",
)


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
    return "эпические и выше, вплоть до ультралегендарных"


# Цвета редкостей для ленты в мини-аппке.
RARITY_COLORS: dict[str, str] = {
    "epic": "#a855f7",
    "mythic": "#ef4444",
    "legendary": "#eab308",
    "secret": "#64748b",
    "ultra": "#22d3ee",
    "teacher": "#a16207",
    "rare": "#94a3b8",
    "superrare": "#3b82f6",
}


def case_pool() -> list[dict]:
    """Карты, которые могут выпасть из кейса, — для ленты в мини-аппке."""
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
                    "color": RARITY_COLORS.get(rarity, "#334155"),
                }
            )
    return pool
