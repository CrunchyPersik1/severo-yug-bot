"""Юга-кликер: тапаешь, ставишь автокликеры, качаешь улучшения.

Игра конечная: за всё время можно получить не больше 15 000 000 Югов,
дальше прибыль просто останавливается. Юги обмениваются на кейсы —
100 000 за штуку.
"""

from __future__ import annotations

import math

from typing import Any

MAX_TOTAL = 1e15                # потолка фактически нет: раньше 2.5 млн
                                # мешали выполнять задания на накопление
CASE_PRICE = 100_000.0          # Югов за один кейс
BASE_TAP = 1.0                  # сколько даёт один тап изначально
OFFLINE_CAP_SECONDS = 8 * 3600  # больше 8 часов офлайна не копим

# --- античит --------------------------------------------------------------- #
# Человек не может тапать быстрее этого. Всё сверх нормы не засчитывается,
# а запросы с наглым перебором пишутся в журнал.
MAX_TAPS_PER_SECOND = 15.0
TAP_BURST = 30.0               # запас токенов, чтобы короткие рывки прощались
FLAG_FROM = 5                  # с этого перебора пишем в журнал

# Здания: растят доход в секунду. Цена растёт с каждой покупкой.
BUILDINGS: tuple[dict[str, Any], ...] = (
    {"id": "cur", "name": "Курсор", "emoji": "👆", "cost": 15, "prod": 0.1,
     "grow": 1.15, "note": "тапает за тебя"},
    {"id": "yuga", "name": "Юга-мастер", "emoji": "🧑", "cost": 100, "prod": 0.8,
     "grow": 1.15, "note": "делает Юги руками"},
    {"id": "farm", "name": "Ферма", "emoji": "🌱", "cost": 1_100, "prod": 5,
     "grow": 1.15, "note": "выращивает Юги"},
    {"id": "mine", "name": "Шахта", "emoji": "⛏", "cost": 12_000, "prod": 30,
     "grow": 1.15, "note": "добывает из-под земли"},
    {"id": "factory", "name": "Фабрика", "emoji": "🏭", "cost": 130_000, "prod": 180,
     "grow": 1.15, "note": "штампует потоком"},
    {"id": "bank", "name": "Банк", "emoji": "🏦", "cost": 1_400_000, "prod": 1_100,
     "grow": 1.15, "note": "начисляет проценты"},
    {"id": "portal", "name": "Портал", "emoji": "🌀", "cost": 20_000_000, "prod": 7_500,
     "grow": 1.15, "note": "тянет из другого мира"},
    {"id": "prism", "name": "Призма", "emoji": "💎", "cost": 330_000_000, "prod": 50_000,
     "grow": 1.15, "note": "преломляет свет в Юги"},
    {"id": "ship", "name": "Корабль", "emoji": "🚀", "cost": 5_100_000_000, "prod": 350_000,
     "grow": 1.15, "note": "везёт Юги с орбиты"},
    {"id": "lab", "name": "Лаборатория", "emoji": "⚗️", "cost": 75_000_000_000, "prod": 2_500_000,
     "grow": 1.15, "note": "синтезирует Юги"},
    {"id": "time", "name": "Машина времени", "emoji": "⏳", "cost": 1_000_000_000_000, "prod": 18_000_000,
     "grow": 1.15, "note": "берёт из будущего"},
    {"id": "anti", "name": "Антиматерия", "emoji": "🌌", "cost": 14_000_000_000_000, "prod": 130_000_000,
     "grow": 1.15, "note": "аннигилирует в Юги"},
    {"id": "chance", "name": "Делатель удачи", "emoji": "🍀", "cost": 170_000_000_000_000, "prod": 900_000_000,
     "grow": 1.15, "note": "везение в чистом виде"},
    {"id": "engine", "name": "Фрактал", "emoji": "🧩", "cost": 2_100_000_000_000_000, "prod": 6_000_000_000,
     "grow": 1.15, "note": "бесконечная копия себя"},
    {"id": "idle", "name": "Идлверс", "emoji": "💫", "cost": 26_000_000_000_000_000, "prod": 45_000_000_000,
     "grow": 1.15, "note": "целая вселенная Югов"},
)

# Улучшения: старые четыре + древо по зданиям + общие.
_OLD_UPGRADES: tuple[dict[str, Any], ...] = (
    {"id": "ruka", "name": "Вторая рука", "emoji": "✋", "cost": 5_000,
     "tap_mult": 2.0, "prod_mult": 1.0, "note": "тап ×2"},
    {"id": "tetrad", "name": "Тетрадь в клетку", "emoji": "📓", "cost": 40_000,
     "tap_mult": 1.0, "prod_mult": 1.5, "note": "доход ×1.5"},
    {"id": "prodlenka", "name": "Продлёнка", "emoji": "🕔", "cost": 300_000,
     "tap_mult": 1.0, "prod_mult": 1.5, "note": "доход ×1.5"},
    {"id": "chetvert", "name": "Пятая четверть", "emoji": "🔥", "cost": 1_500_000,
     "tap_mult": 3.0, "prod_mult": 2.0, "note": "тап ×3, доход ×2"},
)

# 6 уровней на каждое здание (нужно владеть N штуками) + 10 общих = 100
_NEED = (5, 10, 25, 50, 100, 150)
_PRICE = (20, 200, 2_000, 20_000, 200_000, 2_000_000)

UPGRADES: tuple[dict[str, Any], ...] = _OLD_UPGRADES + tuple(
    {
        "id": b["id"] + "_lvl" + str(i),
        "name": b["name"] + " ×2",
        "emoji": b["emoji"],
        "cost": int(float(b["cost"]) * _PRICE[i]),
        "tap_mult": 1.0,
        "prod_mult": 2.0,
        "building": b["id"],
        "need": _NEED[i],
        "note": "нужно " + str(_NEED[i]) + " шт, доход вдвое",
    }
    for b in BUILDINGS
    for i in range(6)
) + tuple(
    {
        "id": "g" + str(i),
        "name": "Общий рост +" + str(5 * (i + 1)) + "%",
        "emoji": "🌟",
        "cost": int(50_000 * (30 ** i)),
        "tap_mult": 1.0,
        "prod_mult": 1.0 + 0.05 * (i + 1),
        "note": "весь доход +" + str(5 * (i + 1)) + "%",
    }
    for i in range(10)
)

BUILDINGS_BY_ID: dict[str, dict[str, Any]] = {b["id"]: b for b in BUILDINGS}
UPGRADES_BY_ID: dict[str, dict[str, Any]] = {u["id"]: u for u in UPGRADES}


def tap_bucket(window_at: Any, tokens: Any, now: Any) -> float:
    """Сколько тапов игрок имеет право сделать прямо сейчас.

    Простая «лейка»: токены копятся со временем, каждый тап тратит один.
    Так робот, долбящий 300 тапов в секунду, упрётся в потолок, а живой
    человек с быстрыми пальцами — нет.
    """
    if window_at is None:
        return TAP_BURST
    elapsed = max(0.0, (now - window_at).total_seconds())
    return min(TAP_BURST, max(0.0, float(tokens or 0)) + elapsed * MAX_TAPS_PER_SECOND)


def tap_take(available: float, count: int) -> tuple[int, float, int]:
    """Сколько тапов засчитать. Возвращает (принято, остаток токенов, отклонено)."""
    want = max(0, int(count))
    take = int(min(float(want), max(0.0, float(available))))
    return take, max(0.0, float(available) - take), want - take


def building_cost(spec: dict[str, Any], count: int) -> float:
    """Цена следующей такой постройки: каждая покупка дороже предыдущей."""
    return float(spec["cost"]) * (float(spec["grow"]) ** max(0, int(count)))


def tap_power(upgrades: list[str]) -> float:
    power = BASE_TAP
    for upgrade_id in upgrades:
        spec = UPGRADES_BY_ID.get(upgrade_id)
        if spec is not None:
            power *= float(spec["tap_mult"])
    return power


def per_second(buildings: dict[str, Any], upgrades: list[str]) -> float:
    """Доход в секунду: производство зданий × их апгрейды × общие."""
    per_building: dict[str, float] = {}
    common = 1.0
    for upgrade_id in upgrades:
        spec = UPGRADES_BY_ID.get(str(upgrade_id))
        if spec is None:
            continue
        target = spec.get("building")
        if target:
            per_building[target] = per_building.get(target, 1.0) * float(
                spec.get("prod_mult", 1.0)
            )
        else:
            common *= float(spec.get("prod_mult", 1.0))
    total = 0.0
    for building_id, count in buildings.items():
        spec = BUILDINGS_BY_ID.get(str(building_id))
        if spec is None:
            continue
        total += (
            float(spec["prod"])
            * int(count or 0)
            * per_building.get(str(building_id), 1.0)
        )
    return total * common


def left_to_earn(total: float) -> float:
    """Сколько ещё можно получить до потолка."""
    return max(0.0, MAX_TOTAL - float(total or 0))


def add_earned(total: float, balance: float, gain: float) -> tuple[float, float]:
    """Начисляет доход с учётом потолка. Возвращает (total, balance)."""
    gain = max(0.0, float(gain))
    room = left_to_earn(total)
    gain = min(gain, room)
    return float(total) + gain, float(balance) + gain


def fmt(value: float) -> str:
    """Числа покороче: 12.3K, 4.5M."""
    value = float(value)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:.0f}"


def daily_report(state: dict[str, Any]) -> str:
    return (
        f"Югов: {fmt(state['balance'])} · в секунду: {fmt(state['per_second'])}"
    )
