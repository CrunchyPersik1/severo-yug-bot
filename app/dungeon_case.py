
"""Оружейные кейсы подземелья: покупаются за очки, кладут ствол в сумку героя.

Каталог оружия повторяет клиентскую генерацию (3 вида × 10 тиров × 5 вариантов),
чтобы id и статы совпадали с тем, что рисует страница подземелья.
"""

from __future__ import annotations

import random
from typing import Any

from . import dungeon as dungeon_mod

ADJ = (
    "Ржавый", "Кованый", "Стальной", "Закалённый", "Рунный",
    "Серебряный", "Золотой", "Пламенный", "Драконий", "Бездонный",
)
KINDS: dict[str, tuple[tuple[str, ...], int, str]] = {
    "sword": (("Клинок", "Меч", "Палаш", "Тесак", "Ятаган"), 82, "мечник"),
    "bow": (("Лук", "Арбалет", "Лонгбоу", "Самострел", "Тяжёлый лук"), 150, "лучник"),
    "staff": (("Посох", "Жезл", "Скипетр", "Тотем", "Жезл-клинок"), 125, "маг"),
}
MAX_TIER = 9

# Кейсы: bonus поднимает доступный тир относительно уровня героя
CASES: tuple[dict[str, Any], ...] = (
    {
        "sku": "wcase_1",
        "title": "Ящик оружия",
        "subtitle": "Ствол по твоему уровню · тир I–X",
        "price": 25_000,
        "bonus": 0,
    },
    {
        "sku": "wcase_2",
        "title": "Ящик оружейника",
        "subtitle": "Тиром выше уровня · без мусора",
        "price": 90_000,
        "bonus": 1,
    },
    {
        "sku": "wcase_3",
        "title": "Арсенал подземелья",
        "subtitle": "Топовые тиры · лучший шанс на высокий ранг",
        "price": 300_000,
        "bonus": 2,
    },
)
BY_SKU = {case["sku"]: case for case in CASES}


def stats(weapon_id: str) -> dict[str, Any] | None:
    """Статы оружия по id: dmg/range/spd и подпись."""
    parts = str(weapon_id or "").split("_")
    if len(parts) != 3 or parts[0] not in KINDS:
        return None
    kind = parts[0]
    try:
        tier, variant = int(parts[1]), int(parts[2])
    except ValueError:
        return None
    if not (0 <= tier <= MAX_TIER) or not (0 <= variant < 5):
        return None
    names, base_range, cls = KINDS[kind]
    return {
        "id": weapon_id,
        "kind": kind,
        "cls": cls,
        "tier": tier,
        "variant": variant,
        "name": f"{ADJ[tier]} {names[variant]}",
        "dmg": dungeon_mod.weapon_dmg(tier, variant),
        "range": base_range + tier * 3,
        "spd": round(1.0 - tier * 0.015, 3),
    }


def tier_cap(level: int, bonus: int = 0) -> int:
    """До какого тира достаёт кейс: уровень // 8, но не выше IX."""
    return max(0, min(MAX_TIER, int(level or 1) // 8 + int(bonus)))


def roll(level: int, bonus: int = 0, rng: random.Random | None = None) -> dict[str, Any]:
    """Что выпало: оружие не ниже двух тиров от потолка кейса."""
    rnd = rng or random.Random()
    cap = tier_cap(level, bonus)
    low = max(0, cap - 2)
    tier = rnd.randint(low, cap)
    kind = rnd.choice(tuple(KINDS))
    variant = rnd.randrange(0, 5)
    return stats(f"{kind}_{tier}_{variant}") or stats("sword_0_0")
