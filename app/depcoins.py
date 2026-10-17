"""Деп-коины: дробная валюта для улучшения шансов в апгрейдере.

Заработать можно только на бирже: покупаешь акции «Компании доДеп» за
обычные очки, а продаёшь уже за деп-коины. Курс жёстко привязан к очкам,
поэтому арбитража нет, а суммы выходят маленькие и дробные — вида 5.89456.
"""

from __future__ import annotations

import random
from typing import Any

# Курс деп-коина ПЛАВАЕТ: сколько очков дают за один деп-коин, меняется на
# каждом шаге биржи. Среднее держим около базового, но в коридоре.
DEP_BASE_RATE = 100_000.0
DEP_MIN_RATE = 40_000.0
DEP_MAX_RATE = 260_000.0
DEP_RATE_VOL = 0.035      # разброс шага
DEP_RATE_REVERT = 0.06    # тяга к базовому курсу

POINTS_PER_DEP = DEP_BASE_RATE

# Улучшение шанса в апгрейдере.
BOOST_PRICE = 5      # деп-коинов за одну покупку
MAX_BOOSTS = 2       # больше двух на один апгрейд нельзя
BOOST_STEP = 1.35    # каждая покупка умножает шанс

# Акция, которая платит деп-коинами.
DEP_SLUG = "dodep"
DEP_NAME = "Компания доДеп"
DEP_EMOJI = "🧾"
DEP_BASE = 900
DEP_VOL = 0.026

# Карта за дрифт-комбо.
DRIFT_CARD_ID = "elvira_drift"
DRIFT_NEEDED = 3


def next_rate(rate: float, rng: Any = None) -> float:
    """Один шаг курса. Как биржа: сносит в стороны, но тянет к базовому."""
    rng = rng or random
    rate = float(rate) if rate else DEP_BASE_RATE
    drift = ((DEP_BASE_RATE - rate) / DEP_BASE_RATE) * DEP_RATE_REVERT
    change = rng.uniform(-DEP_RATE_VOL, DEP_RATE_VOL) + drift
    value = rate * (1.0 + change)
    return round(max(DEP_MIN_RATE, min(DEP_MAX_RATE, value)), 5)


def from_points(points: int, rate: float = DEP_BASE_RATE) -> float:
    """Сколько деп-коинов дадут за такую сумму очков по текущему курсу."""
    rate = float(rate) if rate else DEP_BASE_RATE
    return max(0.0, round(float(points) / rate, 5))


def to_points(dep: float, rate: float = DEP_BASE_RATE) -> int:
    return int(round(float(dep) * float(rate or DEP_BASE_RATE)))


def boost_multiplier(boost: int) -> float:
    """Во сколько раз улучшен шанс при стольких покупках."""
    boost = max(0, min(MAX_BOOSTS, int(boost)))
    return BOOST_STEP ** boost


def boost_cost(boost: int) -> int:
    """Цена следующего улучшения в деп-коинах. 0 — больше нельзя."""
    return 0 if max(0, int(boost)) >= MAX_BOOSTS else BOOST_PRICE


def fmt(dep: float) -> str:
    """Деп-коины в виде 5.89456 — пять знаков после точки."""
    return f"{float(dep):.5f}"


def describe_boost(boost: int) -> str:
    boost = max(0, int(boost))
    if boost <= 0:
        return "шанс обычный"
    return f"шанс ×{boost_multiplier(boost):.2f}"
