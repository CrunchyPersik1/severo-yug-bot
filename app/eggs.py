"""Яйца и питомник: инкубация, клетки и их прокачка.

Сетка из 9 клеток. В клетку кладётся яйцо и тикает таймер. Клетки
прокачиваются по двум линиям: шанс редкого пета и скорость таймера.
"""

from __future__ import annotations

import random
from typing import Any

from . import pets

SLOTS = 9

EGG_CATS = "cats"

EGGS: dict[str, dict[str, Any]] = {
    EGG_CATS: {
        "id": EGG_CATS,
        "title": "Яйцо «Коты»",
        "note": "0.01% котость · 1% мэни · 25% патейто · 73.99% люси",
        "price": 350_000,
        "currency": "points",
        "hours": 5,
    },
}

UPGRADES: dict[str, dict[str, Any]] = {
    "chance": {
        "id": "chance",
        "title": "Шанс редкого",
        "note": "+2% за уровень к шансу котости и мэни",
        "price": 150_000,
        "currency": "points",
        "step": 0.02,
        "max": 10,
    },
    "speed": {
        "id": "speed",
        "title": "Скорость",
        "note": "−10% времени инкубации за уровень",
        "price": 200_000,
        "currency": "points",
        "step": 0.10,
        "max": 10,
    },
}

PRICE_GROWTH = 1.6


def egg(egg_id: str = EGG_CATS) -> dict[str, Any]:
    return dict(EGGS.get(str(egg_id), EGGS[EGG_CATS]))


def upgrade_price(kind: str, level: int) -> int:
    """Цена следующего уровня клетки: растёт по 1.6 на каждом шаге."""
    info = UPGRADES.get(str(kind))
    if info is None:
        raise ValueError(f"нет такой прокачки: {kind}")
    level = max(0, int(level))
    return int(round(info["price"] * (PRICE_GROWTH ** level)))


def upgrade_step(kind: str, level: int) -> float:
    info = UPGRADES.get(str(kind))
    if info is None:
        raise ValueError(f"нет такой прокачки: {kind}")
    return float(info["step"]) * max(0, int(level))


def can_upgrade(kind: str, level: int) -> bool:
    info = UPGRADES.get(str(kind))
    return info is not None and int(level) < int(info["max"])


def hatch_seconds(
    egg_id: str = EGG_CATS,
    speed_levels: int = 0,
    pet_bonus: float = 0.0,
) -> int:
    """Сколько секунд ждать. Пет Люси и прокачка клетки складываются."""
    base = float(egg(egg_id)["hours"]) * 3600.0
    cut = min(0.75, upgrade_step("speed", speed_levels) + max(0.0, float(pet_bonus)))
    return max(60, int(round(base * (1.0 - cut))))


def roll_pet(chance_levels: int = 0, pet_bonus: float = 0.0, rng: random.Random | None = None) -> str:
    """Что вылупилось. Прокачка и Яичко поднимают шанс редких, съедая люси."""
    rng = rng or random
    weights = dict(pets.egg_weights())
    lift = 1.0 + upgrade_step("chance", chance_levels) + max(0.0, float(pet_bonus))
    for pet_id in ("kotos", "mani"):
        weights[pet_id] *= lift
    total = sum(weights.values())
    weights = {key: value / total * 100.0 for key, value in weights.items()}
    keys = list(weights)
    return rng.choices(keys, weights=[weights[key] for key in keys], k=1)[0]


def slots() -> int:
    return SLOTS


def payload() -> dict[str, Any]:
    return {
        "slots": SLOTS,
        "eggs": [dict(item) for item in EGGS.values()],
        "upgrades": [dict(item) for item in UPGRADES.values()],
        "prices": {kind: upgrade_price(kind, 0) for kind in UPGRADES},
    }
