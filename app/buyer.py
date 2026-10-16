"""Скупщик: скупает любые карты, но платит чуть ниже рынка.

Игроку не надо ждать покупателя и платить комиссию — скупщик берёт сразу,
зато дешевле. Никаких лотов, торгов и репутации.
"""

from __future__ import annotations

from typing import Any

from .cards import Card, get_card
from .market import market_price

# Сколько от рынка платит скупщик. 0.90 — на 10% дешевле рынка.
BUYER_RATE = 0.90


def price(card: Card, bonus: dict[str, int] | None = None) -> int:
    """Сколько скупщик даст за эту карту."""
    return max(1, int(market_price(card, bonus) * BUYER_RATE))


def loss(card: Card, bonus: dict[str, int] | None = None) -> int:
    """Сколько игрок теряет по сравнению с рынком."""
    return max(0, market_price(card, bonus) - price(card, bonus))


def describe() -> str:
    return f"Скупщик платит {int(BUYER_RATE * 100)}% от рыночной цены."


def card_payload(card: Card, count: int = 1, bonus: dict[str, int] | None = None) -> dict[str, Any]:
    from .cards import image_url

    return {
        "id": card.card_id,
        "name": card.display_name,
        "emoji": card.rarity_emoji,
        "rarity": card.rarity_title,
        "rarity_key": card.rarity,
        "hp": card.hp,
        "atk": card.atk,
        "market": market_price(card, bonus),
        "price": price(card, bonus),
        "count": count,
        "image": image_url(card.card_id),
    }


def get(card_id: str) -> Card:
    return get_card(card_id)
