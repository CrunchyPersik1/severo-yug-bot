"""Недельный ивент «Звёздочка».

Звёздочка упала на школьный двор и рассыпалась на осколки. Каждый осколок —
квест. Собери 30 из 49 (по 7 в день) и открой главный квест.

Квесты считаются по УЖЕ существующим счётчикам игры: на старте квеста
запоминаем «сколько было», а прогресс — это разница. Ничего не надо
перехватывать в обработчиках, поэтому ивент не может сломать игру.
"""

from __future__ import annotations

from typing import Any

DAYS = 7
QUESTS_PER_DAY = 7
NEED = 30

# Главный квест: что положить в копилку Звёздочки.
MAIN_DROPS = 5
MAIN_ROULETTE = 5
MAIN_CASES = 5
MAIN_POINTS = 1_000_000

# Бонус на время ивента: каждый день +3/+3 к обычным лимитам, разом.
DAILY_DROPS = 3
DAILY_ROULETTE = 3

# Источник прогресса -> SQL-счётчик (всегда «сколько всего было»).
SOURCES: dict[str, str] = {
    "drops": "select count(*) from drops where user_id = $1",
    "upgrades": "select count(*) from upgrader_log where user_id = $1",
    "sold": "select count(*) from buyer_log where user_id = $1",
    "casino": "select count(*) from casino_log where user_id = $1",
    "deals": "select count(*) from history where buyer_id = $1 or seller_id = $1",
    "shop": "select count(*) from shop_log where user_id = $1",
    "taps": "select coalesce(taps, 0) from yugi where user_id = $1",
}

# Базовые требования: с каждым днём чуть больше.
BASE_NEED: dict[str, int] = {
    "drops": 2,
    "upgrades": 1,
    "sold": 3,
    "casino": 2,
    "deals": 1,
    "shop": 1,
    "taps": 200,
}

TITLES: dict[str, str] = {
    "drops": "Выбей карты «Северо-Юг»",
    "upgrades": "Сделай апгрейды в апгрейдере",
    "sold": "Продай карты скупщику",
    "casino": "Сыграй в казино",
    "deals": "Заключи сделки на рынке",
    "shop": "Купи что-нибудь в магазине",
    "taps": "Потапай в Юга-кликере",
}

ORDER: tuple[str, ...] = tuple(SOURCES)


def need_for(source: str, day: int) -> int:
    """Сколько нужно сделать за день day (1..7)."""
    day = max(1, min(DAYS, int(day)))
    base = BASE_NEED.get(source, 1)
    if source == "taps":
        return base * day
    if source in ("upgrades", "casino", "deals"):
        return base + (day - 1) // 2
    return base + (day - 1)


def reward_for(day: int, index: int) -> dict[str, Any]:
    """Награда за квест: очки, а каждый пятый ещё и кейс."""
    day = max(1, min(DAYS, int(day)))
    points = 12_000 + day * 3_000 + (index % 3) * 2_000
    reward: dict[str, Any] = {"points": points}
    if (day + index) % 5 == 0:
        reward["cases"] = 1
    return reward


def reward_text(reward: dict[str, Any]) -> str:
    parts = []
    if reward.get("points"):
        parts.append(f"{int(reward['points']):,}".replace(",", " ") + " очков")
    if reward.get("cases"):
        parts.append(f"{int(reward['cases'])} кейс(ов)")
    return " + ".join(parts) or "—"


def day_of(started: Any, now: Any) -> int:
    """Какой сейчас день ивента (1..DAYS). 0 — ивент ещё не начался."""
    if started is None:
        return 0
    delta = (now - started).total_seconds()
    if delta < 0:
        return 0
    return min(DAYS, int(delta // 86400) + 1)


def is_over(ends: Any, now: Any) -> bool:
    return ends is not None and now >= ends
