"""Казино: ставка очками или картой на красное, чёрное или зелёное.

Правила:
  красное и чёрное — выигрыш x2, зелёное — x5 (но выпадает ~1 раз на 50);
  проигрыш очков — ставка возвращается только на треть;
  проигрыш карты — 20% удаление, 80% ухудшение;
  победа картой — улучшение, зелёное — улучшение до максимума;
  очень редкую проигранную карту можно выкупить за двойную цену.
"""

from __future__ import annotations

import random

COLOR_RED = "red"
COLOR_BLACK = "black"
COLOR_GREEN = "green"

COLORS: dict[str, str] = {
    COLOR_RED: "🔴 Красное",
    COLOR_BLACK: "⚫ Чёрное",
    COLOR_GREEN: "🟢 Зелёное",
}

# Зелёное — примерно 1 шанс на 50, остальное делится поровну.
GREEN_CHANCE = 0.02
RED_CHANCE = 0.49
BLACK_CHANCE = 0.49

RED_MULT = 2
GREEN_MULT = 5
LOSS_DIVISOR = 3

DELETE_CHANCE = 0.20
WORSEN_CHANCE = 0.80

BUYBACK_MULT = 2
BUYBACK_MINUTES = 10

STATS: tuple[str, ...] = ("atk", "hp", "def")
MAX_BONUS: dict[str, int] = {"atk": 30, "hp": 30, "def": 30}
WIN_STEP = (10, 25)
LOSE_STEP = (10, 20)
BONUS_FLOOR = -50

# Выкупить можно только по-настоящему редкое.
BUYBACK_RARITIES = frozenset({"legendary", "secret", "ultra"})

MIN_BET = 100
MAX_BET = 100_000


def color_title(color: str) -> str:
    return COLORS.get(color, color)


def roll_color(rng: random.Random | None = None) -> str:
    rng = rng or random
    return rng.choices(
        [COLOR_RED, COLOR_BLACK, COLOR_GREEN],
        weights=[RED_CHANCE, BLACK_CHANCE, GREEN_CHANCE],
        k=1,
    )[0]


def is_win(color: str, rolled: str) -> bool:
    return color == rolled


def points_win(bet: int, color: str) -> int:
    """Сколько очков вернётся при победе."""
    return int(bet) * (GREEN_MULT if color == COLOR_GREEN else RED_MULT)


def points_lose(bet: int) -> int:
    """При проигрыше возвращается только треть ставки."""
    return int(bet) // LOSS_DIVISOR


def card_fate(rng: random.Random | None = None) -> str:
    """Что случится с проигранной картой: удаление или ухудшение."""
    rng = rng or random
    return "delete" if rng.random() < DELETE_CHANCE else "worsen"


def random_win_bonus(rng: random.Random | None = None) -> dict[str, int]:
    rng = rng or random
    stat = rng.choice(STATS)
    return {stat: rng.randint(*WIN_STEP)}


def random_lose_bonus(rng: random.Random | None = None) -> dict[str, int]:
    rng = rng or random
    stat = rng.choice(STATS)
    return {stat: -rng.randint(*LOSE_STEP)}


def apply_bonus(current: dict[str, int] | None, delta: dict[str, int]) -> dict[str, int]:
    """Складывает бонусы казино, не давая упасть ниже пола."""
    result = {stat: int(value) for stat, value in (current or {}).items()}
    for stat, value in delta.items():
        result[stat] = max(BONUS_FLOOR, result.get(stat, 0) + int(value))
    return {stat: value for stat, value in result.items() if value}


def can_buyback(rarity: str) -> bool:
    return rarity in BUYBACK_RARITIES


def describe_bonus(bonus: dict[str, int] | None) -> str:
    labels = {"atk": "атака", "hp": "HP", "def": "защита"}
    if not bonus:
        return "без изменений"
    return ", ".join(f"{labels.get(k, k)} {v:+d}%" for k, v in bonus.items())
