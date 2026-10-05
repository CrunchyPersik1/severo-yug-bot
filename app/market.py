"""Рыночная логика: цены, эффективные статы, репутация, разбор ссылок на карты.

Чистые функции — их можно тестировать без БД и Telegram.
"""

from __future__ import annotations

import re
from typing import Any

from .cards import Card

# --- коэффициенты редкости -------------------------------------------------- #
RARITY_COEF: dict[str, float] = {
    "rare": 1.0,
    "superrare": 1.5,
    "epic": 2.0,
    "mythic": 2.5,
    "legendary": 3.0,
    "secret": 3.5,   # в ТЗ коэффициент не указан — взял между легендарным и ультра
    "ultra": 4.0,
}

# --- репутация -------------------------------------------------------------- #
RATING_START = 5.0
RATING_MAX = 10.0
RATING_MIN = 0.0
RATING_MIN_TO_SELL = 1.5          # ниже — лоты выставлять нельзя
SUSPECT_RATIO = 0.20              # < 20% от рыночной: -1.0 и пометка «подозрительный»
CHEAP_RATIO = 0.50                # < 50% от рыночной: -0.5
HONEST_RATIO = 0.80               # >= 80%: +0.1 продавцу
HONEST_GAIN = 0.1
HONEST_GAIN_PER_DAY = 1.0
SUSPECT_PENALTY = -1.0
CHEAP_PENALTY = -0.5

# --- рынок ------------------------------------------------------------------ #
MARKET_FEE = 0.05                 # 5% сгорает
DEF_CAP = 60                      # защита не может съесть больше 60% урона
UPGRADE_MULT_MIN = 0.5
# Проценты улучшений весят в цене вдвое: топовый набор поднимает цену к ~2.3x
# от базы (а вместе с редкостью — до 5x и выше, у ульты больше).
UPGRADE_PRICE_FACTOR = 2.0

_HANDLE_NUMBER = re.compile(r"^(?:#|inventory:|inv:)?(\d+)$")
_HANDLE_CASE = re.compile(r"^(?:#|case:)?c(\d+)$", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Статы
# --------------------------------------------------------------------------- #


def sum_bonus(*bonuses: dict[str, int] | None) -> dict[str, int]:
    """Складывает проценты нескольких улучшений по каждому стату."""
    total: dict[str, int] = {}
    for bonus in bonuses:
        if not bonus:
            continue
        for stat, value in bonus.items():
            total[stat] = total.get(stat, 0) + int(value)
    return {stat: value for stat, value in total.items() if value}


def effective_stats(card: Card, bonus: dict[str, int] | None) -> dict[str, int]:
    """Атака и HP множатся на проценты, защита — это и есть процент снижения урона."""
    bonus = bonus or {}
    atk = max(1, round(card.atk * (100 + bonus.get("atk", 0)) / 100))
    hp = max(1, round(card.hp * (100 + bonus.get("hp", 0)) / 100))
    defense = max(0, min(DEF_CAP, int(bonus.get("def", 0))))
    return {"atk": atk, "hp": hp, "def": defense}


# --------------------------------------------------------------------------- #
# Цена
# --------------------------------------------------------------------------- #


def rarity_coef(card: Card) -> float:
    return RARITY_COEF.get(card.rarity, 1.0)


def upgrade_multiplier(bonus: dict[str, int] | None) -> float:
    total = sum(int(v) for v in (bonus or {}).values())
    return max(UPGRADE_MULT_MIN, 1 + total * UPGRADE_PRICE_FACTOR / 100)


def market_price(card: Card, bonus: dict[str, int] | None = None) -> int:
    """base_price * коэффициент редкости * бонус от улучшений."""
    return max(1, round(card.points * rarity_coef(card) * upgrade_multiplier(bonus)))


def market_fee(price: int) -> int:
    return int(price * MARKET_FEE)


def seller_income(price: int) -> int:
    return int(price) - market_fee(price)


def price_ratio(price: int, reference: int) -> float:
    if reference <= 0:
        return 1.0
    return price / reference


def listing_penalty(ratio: float) -> tuple[float, bool]:
    """Штраф к репутации за демпинг и признак «подозрительного» лота."""
    if ratio < SUSPECT_RATIO:
        return SUSPECT_PENALTY, True
    if ratio < CHEAP_RATIO:
        return CHEAP_PENALTY, False
    return 0.0, False


def is_honest_deal(price: int, reference: int) -> bool:
    return price_ratio(price, reference) >= HONEST_RATIO


def clamp_rating(value: float) -> float:
    return round(max(RATING_MIN, min(RATING_MAX, value)), 2)


def can_sell(rating: float) -> bool:
    return rating >= RATING_MIN_TO_SELL


# --------------------------------------------------------------------------- #
# Ссылки на карты: #oleg (стак) и #12 (улучшенная копия)
# --------------------------------------------------------------------------- #


def parse_handle(raw: str) -> tuple[str, Any] | None:
    """'#c3' -> ('case', 3); '#12' -> ('inventory', 12); '#oleg' -> ('card', 'oleg')."""
    text = (raw or "").strip()
    if not text:
        return None
    case = _HANDLE_CASE.match(text)
    if case:
        return "case", int(case.group(1))
    match = _HANDLE_NUMBER.match(text)
    if match:
        return "inventory", int(match.group(1))
    slug = text.lstrip("#").strip().lower()
    return ("card", slug) if slug else None


def card_handle(card_id: str) -> str:
    return f"#{card_id}"


def inventory_handle(inventory_id: int) -> str:
    return f"#{inventory_id}"


def case_handle(case_id: int) -> str:
    return f"#c{case_id}"


def describe_bonus(bonus: dict[str, int] | None) -> str:
    if not bonus:
        return "без улучшений"
    labels = {"atk": "атака", "hp": "HP", "def": "защита"}
    return ", ".join(f"{labels.get(k, k)} {v:+d}%" for k, v in bonus.items())
