"""Кейсы: закрытый предмет, из которого выпадает карта эпической редкости и выше."""

from __future__ import annotations

import random

from .cards import CARDS_BY_RARITY, Card

# Рыночная цена кейса фиксирована и не зависит от того, что внутри.
CASE_PRICE = 5000

# Ниже эпической из кейса не выпадает ничего.
CASE_RARITY_WEIGHTS: dict[str, float] = {
    "epic": 0.60,
    "mythic": 0.28,
    "legendary": 0.08,
    "secret": 0.03,
    "ultra": 0.01,
}

CASE_RARITY_ORDER: tuple[str, ...] = ("epic", "mythic", "legendary", "secret", "ultra")


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
