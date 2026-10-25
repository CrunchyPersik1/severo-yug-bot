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
    {"id": "parta", "name": "Парта", "emoji": "🪑", "cost": 200, "prod": 0.5, "grow": 1.13,
     "note": "за ней сидят"},
    {"id": "ryukzak", "name": "Рюкзак", "emoji": "🎒", "cost": 1_200, "prod": 3, "grow": 1.14,
     "note": "тяжёлый, но полезный"},
    {"id": "klass", "name": "Класс", "emoji": "🏫", "cost": 6_000, "prod": 15, "grow": 1.15,
     "note": "целый кабинет"},
    {"id": "stolovaya", "name": "Столовая", "emoji": "🍽️", "cost": 30_000, "prod": 80, "grow": 1.16,
     "note": "кормит всех"},
    {"id": "sportzal", "name": "Спортзал", "emoji": "🏀", "cost": 150_000, "prod": 450, "grow": 1.17,
     "note": "качалка и мячи"},
    {"id": "biblioteka", "name": "Библиотека", "emoji": "📚", "cost": 800_000, "prod": 2_500, "grow": 1.18,
     "note": "тишина и знания"},
)

# Улучшения: покупаются один раз, множат тап и доход.
UPGRADES: tuple[dict[str, Any], ...] = (
    {"id": "ruka", "name": "Вторая рука", "emoji": "✋", "cost": 5_000,
     "tap_mult": 2.0, "prod_mult": 1.0, "note": "тап ×2"},
    {"id": "tetrad", "name": "Тетрадь в клетку", "emoji": "📓", "cost": 40_000,
     "tap_mult": 1.0, "prod_mult": 1.5, "note": "доход ×1.5"},
    {"id": "prodlenka", "name": "Продлёнка", "emoji": "🕔", "cost": 300_000,
     "tap_mult": 1.0, "prod_mult": 1.5, "note": "доход ×1.5"},
    {"id": "chetvert", "name": "Пятая четверть", "emoji": "🔥", "cost": 1_500_000,
     "tap_mult": 3.0, "prod_mult": 2.0, "note": "тап ×3, доход ×2"},
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
    total = 0.0
    for building_id, count in buildings.items():
        spec = BUILDINGS_BY_ID.get(building_id)
        if spec is not None:
            total += float(spec["prod"]) * int(count or 0)
    mult = 1.0
    for upgrade_id in upgrades:
        spec = UPGRADES_BY_ID.get(upgrade_id)
        if spec is not None:
            mult *= float(spec["prod_mult"])
    return total * mult


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
