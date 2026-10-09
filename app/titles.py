"""Титулы игрока: чем глубже в игре, тем выше звание.

Считаем условные «очки вклада» по всему, чем игрок занимался: коллекция,
улучшения, бои, казино, рынок, магазин, подарки, приглашённые, выпадения.
"""

from __future__ import annotations

from typing import Any

WEIGHTS: dict[str, int] = {
    "unique_cards": 1,      # каждая новая карта
    "total_cards": 1,       # каждая копия
    "upgraded": 4,          # улучшенные копии
    "wins": 2,              # победы в PvP
    "kills": 1,             # убитые чужие карты
    "casino_bets": 1,       # ставки в казино
    "market_deals": 2,      # сделки на рынке
    "shop_buys": 2,         # покупки в магазине
    "gifts_sent": 2,        # подарки
    "invited": 5,           # приглашённые друзья
    "drops": 1,             # выпадения «Северо-Юг»
    "promos": 3,            # промокоды
}

TITLES: tuple[tuple[int, str], ...] = (
    (0, "Новичок"),
    (25, "Первоклашка"),
    (70, "Школьник"),
    (160, "Активист"),
    (320, "Отличник"),
    (600, "Староста"),
    (1000, "Выпускник"),
    (1800, "Легенда школы"),
    (3000, "Директор Севера-Юга"),
    (5000, "Хранитель Севера-Юга"),
)


def score(profile: dict[str, Any]) -> int:
    total = 0
    for key, weight in WEIGHTS.items():
        total += int(profile.get(key) or 0) * weight
    return total


def title_for(profile: dict[str, Any]) -> str:
    points = score(profile)
    name = TITLES[0][1]
    for threshold, title in TITLES:
        if points >= threshold:
            name = title
    return name


def progress(profile: dict[str, Any]) -> tuple[int, int, int]:
    """(очки вклада, порог текущего титула, порог следующего или 0)."""
    points = score(profile)
    current = 0
    nxt = 0
    for index, (threshold, _) in enumerate(TITLES):
        if points >= threshold:
            current = threshold
            nxt = TITLES[index + 1][0] if index + 1 < len(TITLES) else 0
        else:
            break
    return points, current, nxt
