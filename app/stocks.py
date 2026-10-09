"""Биржа «Северо-Юг»: акции с живым курсом.

Курс общий для всех и двигается шагами раз в TICK_SECONDS. Шаг — симметричный
случайный (без дрейфа), то есть в среднем курс стоит на месте: поднять очки
можно только на реальном росте. Плюс комиссия на вход и выход — она делает
быстрый трейд убыточным, поэтому фармить очки на бирже нельзя.
"""

from __future__ import annotations

import random

TICK_SECONDS = 15
# Если сервис спал, догоняем курс, но не больше этого числа шагов за раз.
MAX_CATCHUP_TICKS = 8

# Комиссия: покупаем дороже курса, продаём дешевле. 3% в каждую сторону.
FEE = 0.03

# Границы, чтобы курс не улетел в ноль или в космос.
FLOOR_MULT = 0.15
CEIL_MULT = 6.0

MAX_SHARES = 100_000

STOCKS: tuple[dict[str, object], ...] = (
    {"slug": "syug", "name": "Северо-Юг", "emoji": "🎴", "base": 1000, "vol": 0.030},
    {"slug": "uchitel", "name": "Учителя Inc.", "emoji": "🟤", "base": 2500, "vol": 0.022},
    {"slug": "misha", "name": "Миша Corp", "emoji": "🥔", "base": 1500, "vol": 0.040},
    {"slug": "ludoman", "name": "Лудоман Казино", "emoji": "🎰", "base": 800, "vol": 0.050},
    {"slug": "kartofan", "name": "Картофан и Ко", "emoji": "🍟", "base": 600, "vol": 0.035},
    {"slug": "zavuch", "name": "Завуч Групп", "emoji": "📋", "base": 3000, "vol": 0.020},
)


def by_slug(slug: str) -> dict[str, object] | None:
    clean = (slug or "").strip().lower()
    for stock in STOCKS:
        if stock["slug"] == clean:
            return stock
    return None


def buy_price(price: int) -> int:
    """Сколько стоит одна акция при покупке (с комиссией)."""
    return max(1, round(int(price) * (1 + FEE)))


def sell_price(price: int) -> int:
    """Сколько дадут за одну акцию при продаже (за вычетом комиссии)."""
    return max(1, round(int(price) * (1 - FEE)))


def next_price(
    price: int, base: int, volatility: float, rng: random.Random | None = None
) -> int:
    """Один шаг курса: симметричный случайный, в пределах коридора."""
    rng = rng or random
    change = rng.uniform(-float(volatility), float(volatility))
    value = int(price) * (1.0 + change)
    low = int(base) * FLOOR_MULT
    high = int(base) * CEIL_MULT
    return int(max(low, min(high, round(value))))


def change_percent(history: list[int]) -> float:
    """Изменение за показанный отрезок истории, в процентах."""
    if len(history) < 2 or history[0] <= 0:
        return 0.0
    return (history[-1] - history[0]) / history[0] * 100.0
