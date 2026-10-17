"""Апгрейдер карт в стиле CS:GO.

Кладёшь свою карту в первый слот, выбираешь желаемую во второй — и крутишь
рулетку. Шанс зависит от разницы редкостей: чем жаднее апгрейд, тем он реже.
Например, с эпика на мифика — 20%, а с обычного Олега на ультра-Леру — 0.1%.
"""

from __future__ import annotations

import random
from typing import Any

from .cards import Card, get_card

# Лестница редкостей от дешёвой к дорогой.
LADDER: tuple[str, ...] = (
    "rare",
    "superrare",
    "epic",
    "mythic",
    "legendary",
    "secret",
    "ultimate",
    "ultra",
    "teacher",
)

# Шанс по разнице ступеней (to - from).
STEP_CHANCE: dict[int, float] = {
    -8: 0.94,
    -7: 0.92,
    -6: 0.90,
    -5: 0.88,
    -4: 0.84,
    -3: 0.78,
    -2: 0.70,
    -1: 0.58,
    0: 0.45,
    1: 0.20,
    2: 0.08,
    3: 0.03,
    4: 0.01,
    5: 0.003,
    6: 0.001,
    7: 0.0005,
    8: 0.0002,
}

MIN_CHANCE = 0.0002
MAX_CHANCE = 0.95


def step_index(card: Card) -> int:
    try:
        return LADDER.index(card.rarity)
    except ValueError:
        return 0


def steps(from_card: Card, to_card: Card) -> int:
    return step_index(to_card) - step_index(from_card)


def chance(from_card: Card, to_card: Card) -> float:
    """Шанс получить вторую карту, поставив первую."""
    diff = steps(from_card, to_card)
    if diff in STEP_CHANCE:
        return STEP_CHANCE[diff]
    return MIN_CHANCE if diff > 7 else MAX_CHANCE


def chance_percent(from_card: Card, to_card: Card) -> str:
    value = chance(from_card, to_card) * 100
    if value >= 1:
        return f"{value:.0f}%"
    if value >= 0.1:
        return f"{value:.1f}%"
    return f"{value:.2f}%"


def roll(from_card: Card, to_card: Card, rng: random.Random | None = None) -> bool:
    rng = rng or random
    return rng.random() < chance(from_card, to_card)


def roll_odd(odd: float, rng: random.Random | None = None) -> bool:
    """Бросок по конкретному шансу — например, улучшенному деп-коинами."""
    rng = rng or random
    return rng.random() < max(0.0, min(1.0, float(odd)))


def matrix(cards: list[Card]) -> list[dict[str, Any]]:
    """Таблица шансов для мини-аппки."""
    rows = []
    for source in cards:
        for target in cards:
            rows.append(
                {
                    "from": source.card_id,
                    "to": target.card_id,
                    "chance": round(chance(source, target), 6),
                }
            )
    return rows


def describe(from_card: Card, to_card: Card) -> str:
    diff = steps(from_card, to_card)
    if diff > 0:
        mood = "апгрейд"
    elif diff == 0:
        mood = "равный обмен"
    else:
        mood = "даунгрейд"
    return f"{mood}: {chance_percent(from_card, to_card)}"


def card_payload(card: Card, count: int = 1) -> dict[str, Any]:
    from .cards import image_url
    from .market import market_price

    return {
        "id": card.card_id,
        "name": card.display_name,
        "emoji": card.rarity_emoji,
        "rarity": card.rarity_title,
        "rarity_key": card.rarity,
        "hp": card.hp,
        "atk": card.atk,
        "points": card.points,
        "price": market_price(card),
        "count": count,
        "image": image_url(card.card_id),
    }


def target_payload(card: Card) -> dict[str, Any]:
    return card_payload(card)


def get(card_id: str) -> Card:
    return get_card(card_id)
