
"""Северо-Пасс: сезоны, уровни, цены и пороги очков.

Сезон — календарный месяц по ЕКБ. Очки копятся только от квестов (и
мегаквестов), сбрасываются в первый день месяца. Уровней 50, цена каждого
растёт ступенями, как в ТЗ.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

EKB = timezone(timedelta(hours=5))

LEVELS = 50
LEVEL_COST = {1: 50, 2: 150}
for _level in range(3, 11):
    LEVEL_COST[_level] = 350
for _level in range(11, 41):
    LEVEL_COST[_level] = 950
for _level in range(41, 51):
    LEVEL_COST[_level] = 1250

TOTAL_XP = sum(LEVEL_COST[level] for level in range(1, LEVELS + 1))

# Бонусная награда после 50 уровня: каждые 2800 очков — выбор из двух
BONUS_STEP = 2800
BONUS_GEM_MIN = 19
BONUS_GEM_MAX = 79

# Покупки
PRICE_PLUS_GEMS = 179
PRICE_PREMIUM_GEMS = 240
PRICE_UPGRADE_GEMS = 60
PRICE_PLUS_RUB = 39
PRICE_PREMIUM_RUB = 59
PRICE_UPGRADE_RUB = 19

# Награда за мегаквест в очках пасса
MEGA_XP = 1500
MEGA_XP_HARD = 3000


def season_start(moment: datetime | None = None) -> datetime:
    """Начало текущего сезона: 1-е число месяца, 00:00 по ЕКБ."""
    moment = (moment or datetime.now(timezone.utc)).astimezone(EKB)
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def season_end(moment: datetime | None = None) -> datetime:
    start = season_start(moment)
    year, month = start.year, start.month + 1
    if month > 12:
        year, month = year + 1, 1
    return start.replace(year=year, month=month)


def season_key(moment: datetime | None = None) -> str:
    return season_start(moment).strftime("%Y-%m")


def season_title(moment: datetime | None = None) -> str:
    """Название сезона: тема задаётся в THEMES по номеру месяца."""
    start = season_start(moment)
    theme = THEMES.get(start.month % 12 + 1) or THEMES.get(1)
    return f"{theme['name']} · {start:%m.%Y}"


# Тематика сезонов по месяцам. Первый сезон — «Академия Северо-Южных».
THEMES: dict[int, dict[str, Any]] = {
    1: {
        "id": "academy",
        "name": "Академия Северо-Южных",
        "title": "Лучший из лучших",
        "style": "academy",
    },
}

DEFAULT_THEME = {
    "id": "academy",
    "name": "Академия Северо-Южных",
    "title": "Лучший из лучших",
    "style": "academy",
}


def theme(moment: datetime | None = None) -> dict[str, Any]:
    start = season_start(moment)
    return THEMES.get(start.month % 12 + 1, DEFAULT_THEME)


def level_for(xp: int) -> int:
    """Сколько уровней уже оплачено накопленными очками."""
    left = max(0, int(xp or 0))
    level = 0
    while level < LEVELS and left >= LEVEL_COST[level + 1]:
        left -= LEVEL_COST[level + 1]
        level += 1
    return level


def xp_into_level(xp: int) -> tuple[int, int, int]:
    """(уровень, набрано внутри уровня, нужно для следующего)."""
    left = max(0, int(xp or 0))
    level = 0
    while level < LEVELS and left >= LEVEL_COST[level + 1]:
        left -= LEVEL_COST[level + 1]
        level += 1
    need = LEVEL_COST.get(level + 1, 0) if level < LEVELS else 0
    return level, left, need


def bonus_steps(xp: int) -> int:
    """Сколько наград «после 50» уже заработано."""
    left = max(0, int(xp or 0)) - TOTAL_XP
    return max(0, left // BONUS_STEP)


def bonus_left(xp: int) -> int:
    left = max(0, int(xp or 0)) - TOTAL_XP
    if left <= 0:
        return BONUS_STEP
    return BONUS_STEP - (left % BONUS_STEP)


def seconds_left(moment: datetime | None = None) -> int:
    now = (moment or datetime.now(timezone.utc)).astimezone(EKB)
    return max(0, int((season_end(now) - now).total_seconds()))


def season_info(moment: datetime | None = None) -> dict[str, Any]:
    start = season_start(moment)
    end = season_end(moment)
    return {
        "key": season_key(moment),
        "name": season_title(moment),
        "theme": theme(moment),
        "starts_at": start.isoformat(),
        "ends_at": end.isoformat(),
        "days_left": max(0, (end.date() - (moment or datetime.now(timezone.utc)).astimezone(EKB).date()).days),
    }
