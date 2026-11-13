"""Питомцы: 17 карт-петов, их способности и цены.

Пет — это карта редкости «Премиум» плюс отдельная строка состояния
(уровень, надет/нет). Здесь только каталог и эффекты: никакой базы и
никаких Telegram — чтобы это можно было проверить тестами.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------- #
# Способности. Каждая — набор множителей, которые читают другие системы.
# --------------------------------------------------------------------------- #
#
# kind — к чему применяется:
#   chance_all   множитель ко всем шансам
#   dungeon_mob  урон по мобам в подземелье (пет бьёт вместе с игроком)
#   gems         шанс выпадения кристаллов
#   upgrade_save шанс сохранить карту при провале апгрейдера
#   xp           опыт (подземелье и кликер)
#   pvp_points   очки за победу в PvP
#   pvp_case     кейс за победу в PvP
#   hatch_speed  скорость инкубации
#   yugi         доход кликера
#   egg_luck     шанс редкого пета из яйца
#   weapon       шанс оружия с мобов
#   boss_coins   монеты за босса
#   double_drop  шанс второй карты в «Северо-Юг»
#   case_points  очки за карты из кейсов
#   ultra_luck   шанс ультраредкой карты
#   quest_reward награда за квесты и мегаквест
#   boss_yugi    Юги за победу над боссом


@dataclass(frozen=True)
class Pet:
    id: str
    name: str
    emoji: str
    kind: str
    title: str
    note: str
    # Цена в магазине Санты: за очки или за кристаллы (None — не продаётся).
    price: int = 0
    currency: str = "points"
    # Множитель эффекта за уровень: base + per_level * (level - 1).
    base: float = 0.0
    per_level: float = 0.0
    max_level: int = 10
    egg_chance: float = 0.0   # шанс выпадения из яйца «Коты», %
    rare: bool = False        # дорогой и редкий: участвует в лимитах стока

    def effect(self, level: int = 1) -> float:
        level = max(1, min(self.max_level, int(level)))
        return round(self.base + self.per_level * (level - 1), 4)


PETS: tuple[Pet, ...] = (
    Pet("kotos", "Котость", "🐈‍⬛", "chance_all", "Абсолют",
        "+1000% ко всем шансам в игре", price=0, base=10.0, per_level=0.0,
        egg_chance=0.01, rare=True),
    Pet("mani", "Мэни", "🐱", "dungeon_mob", "Напарник",
        "бьёт мобов в подземелье вместе с тобой", price=120, currency="gems",
        base=10.0, per_level=6.0, egg_chance=1.0, rare=True),
    Pet("rokki", "Рокки", "🐕", "gems", "Кристальный нюх",
        "+25% к шансу кристаллов везде", price=600_000, base=0.25, per_level=0.05),
    Pet("kasper", "Каспер", "👻", "upgrade_save", "Призрак удачи",
        "20% шанс вернуть карту при провале апгрейдера", price=900, currency="gems",
        base=0.20, per_level=0.01, max_level=6, rare=True),
    Pet("oddi", "Одди", "🦉", "xp", "Мудрая сова",
        "+15% опыта в подземелье и кликере", price=250_000, base=0.15, per_level=0.03),
    Pet("leo", "Лео", "🦁", "pvp_points", "Царь арены",
        "+10% очков за победу в PvP", price=180, currency="gems",
        base=0.10, per_level=0.03),
    Pet("dik", "Дик", "🐓", "pvp_case", "Боевой петух",
        "каждая третья победа в PvP даёт ещё кейс", price=300_000, base=1.0, per_level=0.0),
    Pet("lucy", "Люси", "🐰", "hatch_speed", "Прыткая",
        "−20% времени инкубации яйца", price=150_000, base=0.20, per_level=0.04,
        egg_chance=73.99),
    Pet("patejto", "Патейто", "🥔", "yugi", "Картофельный магнат",
        "+10% к Югам в кликере", price=90_000, base=0.10, per_level=0.03,
        egg_chance=25.0),
    Pet("yaichko", "Яичко", "🥚", "egg_luck", "Золотое яйцо",
        "+2% к шансу редкого пета из яйца", price=220_000, base=0.02, per_level=0.01),
    Pet("mysh", "Мыш", "🐭", "weapon", "Находчивый",
        "+5% к шансу оружия с мобов", price=140_000, base=0.05, per_level=0.02),
    Pet("chester", "Честер", "🐺", "boss_coins", "Волчий нюх",
        "+20% монет за босса", price=320_000, base=0.20, per_level=0.05),
    Pet("najda", "Найда", "🐶", "double_drop", "Ищейка",
        "10% шанс на вторую карту в «Северо-Юг»", price=400_000,
        base=0.10, per_level=0.02),
    Pet("mishlen", "Мишлен", "🐈", "case_points", "Сытный",
        "+10% очков за карты из кейсов", price=450_000, base=0.10, per_level=0.03),
    Pet("simona", "Симона", "🐈‍⬛", "ultra_luck", "Тихий шанс",
        "+3% к шансу ультраредкой карты", price=700, currency="gems",
        base=0.03, per_level=0.01),
    Pet("chelsi", "Челси", "🐩", "quest_reward", "Призовая",
        "+25% к награде за квесты и мегаквест", price=500_000, base=0.25, per_level=0.05),
    Pet("lelik", "Лелик", "🦎", "boss_yugi", "Хвостатый",
        "+15% Югов за победу над боссом", price=260_000, base=0.15, per_level=0.04),
)

BY_ID: dict[str, Pet] = {pet.id: pet for pet in PETS}

# Яйцо «Коты»: только эти четыре пета и ровно 100% (0.01 + 1 + 25 + 73.99).
# В ТЗ было 74.99 — это давало 101%, поправили на 73.99.
EGG_POOL: tuple[str, ...] = ("kotos", "mani", "patejto", "lucy")


def get(pet_id: str) -> Pet | None:
    return BY_ID.get(str(pet_id))


def for_egg() -> list[Pet]:
    return [BY_ID[pet_id] for pet_id in EGG_POOL]


def egg_weights() -> dict[str, float]:
    """Шансы яйца в процентах: сумма ровно 100."""
    weights = {pet.id: pet.egg_chance for pet in for_egg()}
    total = sum(weights.values())
    if abs(total - 100.0) > 1e-9:
        raise ValueError(f"шансы яйца не сходятся: {total}")
    return weights


def effect(pet_id: str, level: int = 1) -> float:
    pet = BY_ID.get(str(pet_id))
    return pet.effect(level) if pet is not None else 0.0


def all_effects() -> dict[str, float]:
    """Множители всех петов первого уровня: удобно для проверок."""
    return {pet.id: pet.effect(1) for pet in PETS}


def shop_price(pet: Pet) -> dict[str, Any]:
    return {"price": int(pet.price), "currency": pet.currency}
