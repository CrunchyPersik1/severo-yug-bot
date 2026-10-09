"""Внезапные пам-пампы: раз в час случайная монета взлетает и откатывается.

Подъём занимает пару минут, откат — быстрее. Точное время и монета случайны.
"""

from __future__ import annotations

import random
from datetime import timedelta

# Раз в час, но не ровно: плюс-минус 15 минут.
EVERY_MINUTES = 60.0
JITTER_MINUTES = 15.0
MIN_DELAY_MINUTES = 25.0

# Подъём ~2-3 минуты (доля разрыва за шаг 15 с), откат быстрее.
UP_PULL = 0.28
DOWN_PULL = 0.55

# Насколько взлетает: от +100% до +400% (максимум).
MIN_GAIN = 1.0
MAX_GAIN = 4.0


def next_delay(rng: random.Random | None = None) -> timedelta:
    """Когда запускать следующий памп."""
    rng = rng or random
    minutes = EVERY_MINUTES + rng.uniform(-JITTER_MINUTES, JITTER_MINUTES)
    return timedelta(minutes=max(MIN_DELAY_MINUTES, minutes))


def peak_price(
    price: int, ceiling: int, rng: random.Random | None = None
) -> int:
    """Куда взлетает: текущая + случайные +100%..+400%, но не выше потолка."""
    rng = rng or random
    gain = rng.uniform(MIN_GAIN, MAX_GAIN)
    return max(int(price), min(int(ceiling), round(int(price) * (1 + gain))))


def step_up(price: int, peak: int) -> int:
    if price >= peak:
        return peak
    step = max(1, round((peak - price) * UP_PULL))
    return min(peak, price + step)


def step_down(price: int, home: int) -> int:
    if price <= home:
        return home
    step = max(1, round((price - home) * DOWN_PULL))
    return max(home, price - step)


def has_room(price: int, base: int, ceil_mult: float) -> bool:
    """Есть ли куда расти: у самого потолка пампить бессмысленно."""
    return int(price) < int(int(base) * ceil_mult * 0.7)


def pick(rows: list, rng: random.Random | None = None):
    rng = rng or random
    if not rows:
        return None
    return rng.choice(list(rows))
