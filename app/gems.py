"""Кристаллы с мобов в подземелье.

Мобы живут на странице, поэтому выпадение подтверждает сервер: страница
присылает факт убийства, сервер режет частоту (не чаще раза в минуту) и сам
бросает кости. Так нельзя нафармить кристаллы, дёргая ручку в цикле.
"""

from __future__ import annotations

import random

# Не чаще одной попытки в 10 секунд на игрока.
COOLDOWN_SECONDS = 10

# Шанс зависит от локации, но полого: 0.12% в Опушке, 0.40% в Бездне.
CHANCE_MIN = 0.0012
CHANCE_MAX = 0.0040

# Сколько может выпасть: от 2..6 в первой локации до 10..15 в десятой.
AMOUNT_MIN = 2
AMOUNT_MAX = 15

ZONES = 10


def clamp_zone(value: object) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, min(ZONES - 1, number))


def chance(zone: int) -> float:
    zone = clamp_zone(zone)
    if ZONES <= 1:
        return CHANCE_MIN
    step = (CHANCE_MAX - CHANCE_MIN) / (ZONES - 1)
    return CHANCE_MIN + step * zone


def amount_range(zone: int) -> tuple[int, int]:
    zone = clamp_zone(zone)
    low = AMOUNT_MIN + zone // 3
    high = min(AMOUNT_MAX, AMOUNT_MIN + 4 + zone)
    return low, max(low, high)


def roll(zone: int, rng: random.Random | None = None, boost: float = 1.0) -> int:
    """Сколько кристаллов выпало. 0 — ничего. boost — бонус пета (Рокки)."""
    rng = rng or random
    if rng.random() >= min(0.9, chance(zone) * max(0.0, float(boost))):
        return 0
    low, high = amount_range(zone)
    return rng.randint(low, high)
