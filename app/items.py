"""30 улучшений: 10 аур, 10 фонов, 10 эффектов.

Улучшения НЕ имеют уровней. Все внутри категории равновероятны: может выпасть
имба, может мусор. Бонусы — проценты, могут быть отрицательными.
Аура множит ВСЕ статы, фон и эффект — ОДИН стат.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

SLOT_AURA = "aura"
SLOT_BACKGROUND = "background"
SLOT_EFFECT = "effect"
SLOTS: tuple[str, ...] = (SLOT_AURA, SLOT_BACKGROUND, SLOT_EFFECT)

SLOT_TITLES = {
    SLOT_AURA: "Аура",
    SLOT_BACKGROUND: "Фон",
    SLOT_EFFECT: "Эффект",
}

SLOT_ICONS = {
    SLOT_AURA: "🌟",
    SLOT_BACKGROUND: "🌌",
    SLOT_EFFECT: "🌀",
}


@dataclass(frozen=True)
class Item:
    id: int
    name: str
    bonus: dict[str, int]

    @property
    def summary(self) -> str:
        parts = []
        for stat in ("atk", "hp", "def"):
            if stat in self.bonus:
                parts.append(f"{STAT_TITLES[stat]} {self.bonus[stat]:+d}%")
        return ", ".join(parts)


STAT_TITLES = {"atk": "атака", "hp": "HP", "def": "защита"}

AURAS: tuple[Item, ...] = (
    Item(1, "Пламя Севера", {"atk": 8, "hp": 8, "def": 8}),
    Item(2, "Ледяная Бездна", {"atk": 4, "hp": 12, "def": 4}),
    Item(3, "Эхо Войны", {"atk": 14, "hp": 2, "def": 2}),
    Item(4, "Северное Сияние", {"atk": 6, "hp": 6, "def": 6}),
    Item(5, "Тень Полюса", {"atk": 16, "hp": -6, "def": 8}),
    Item(6, "Дыхание Мороза", {"atk": -6, "hp": 18, "def": 12}),
    Item(7, "Стальной Ветер", {"atk": 4, "hp": 4, "def": 16}),
    Item(8, "Кровь Земли", {"atk": 10, "hp": 10, "def": -6}),
    Item(9, "Вечный Полдень", {"atk": 12, "hp": 12, "def": 12}),
    Item(10, "Проклятие Стужи", {"atk": 22, "hp": -10, "def": -12}),
)

BACKGROUNDS: tuple[Item, ...] = (
    Item(1, "Полярный Рассвет", {"atk": 12}),
    Item(2, "Глубина Океана", {"hp": 18}),
    Item(3, "Гранитный Щит", {"def": 14}),
    Item(4, "Костяной Трон", {"hp": 25}),
    Item(5, "Кровавая Луна", {"atk": 20}),
    Item(6, "Мёрзлый Панцирь", {"def": 22}),
    Item(7, "Шёпот Тайги", {"hp": 8}),
    Item(8, "Громовая Высь", {"atk": 16}),
    Item(9, "Соляная Пустошь", {"def": 9}),
    Item(10, "Пепельный Закат", {"hp": -10}),
)

EFFECTS: tuple[Item, ...] = (
    Item(1, "Отзвук Битвы", {"atk": 15}),
    Item(2, "Ледяной Узор", {"def": 12}),
    Item(3, "Пламя Души", {"atk": 25}),
    Item(4, "Тень Палача", {"atk": 18}),
    Item(5, "Зов Предков", {"hp": 30}),
    Item(6, "Разлом", {"def": 28}),
    Item(7, "Пыль Времён", {"hp": 14}),
    Item(8, "Стальной Хребет", {"def": 18}),
    Item(9, "Янтарный Свет", {"hp": 22}),
    Item(10, "Гнилой Корень", {"atk": -12}),
)

BY_SLOT: dict[str, tuple[Item, ...]] = {
    SLOT_AURA: AURAS,
    SLOT_BACKGROUND: BACKGROUNDS,
    SLOT_EFFECT: EFFECTS,
}

TABLE_BY_SLOT = {
    SLOT_AURA: "auras",
    SLOT_BACKGROUND: "backgrounds",
    SLOT_EFFECT: "effects",
}


def roll_item(slot: str, rng: random.Random | None = None) -> Item:
    """Равновероятный предмет внутри категории."""
    return (rng or random).choice(BY_SLOT[slot])


def roll_slot(filled: dict[str, Any], rng: random.Random | None = None) -> str | None:
    """Случайный пустой слот. None — все три уже заняты."""
    free = [slot for slot in SLOTS if not filled.get(slot)]
    if not free:
        return None
    return (rng or random).choice(free)


def seed_rows() -> list[tuple[str, list[tuple[int, str, str]]]]:
    """Готовые строки для upsert в таблицы auras/backgrounds/effects."""
    import json

    return [
        (TABLE_BY_SLOT[slot], [(item.id, item.name, json.dumps(item.bonus)) for item in BY_SLOT[slot]])
        for slot in SLOTS
    ]
