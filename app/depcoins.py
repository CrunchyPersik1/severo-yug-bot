"""Деп-коины: дробная валюта для улучшения шансов в апгрейдере.

Заработать можно только на бирже: покупаешь акции «Компании доДеп» за
обычные очки, а продаёшь уже за деп-коины. Курс жёстко привязан к очкам,
поэтому арбитража нет, а суммы выходят маленькие и дробные — вида 5.89456.
"""

from __future__ import annotations

# Сколько очков «стоит» один деп-коин. Держит экономику: продал акции на
# 500 000 очков — получил 5 деп-коинов, не больше.
POINTS_PER_DEP = 100_000.0

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


def from_points(points: int) -> float:
    """Сколько деп-коинов причитается за такую сумму очков."""
    return max(0.0, round(float(points) / POINTS_PER_DEP, 5))


def to_points(dep: float) -> int:
    return int(round(float(dep) * POINTS_PER_DEP))


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
