
"""Квесты Северо-Пасса: три лёгких, три средних, один сложный в день.

Плюс два дополнительных квеста для владельцев сп+ (видят все, получить
очки могут только они). Задания копятся до конца сезона: невыполненные
остаются доступными, поэтому очки можно добрать в конце месяца.
"""

from __future__ import annotations

import hashlib
import random
from datetime import date
from typing import Any

XP_LIGHT = 200
XP_MEDIUM = 500
XP_HARD = 1000

TIERS: dict[str, dict[str, Any]] = {
    "light": {"xp": XP_LIGHT, "title": "лёгкое"},
    "medium": {"xp": XP_MEDIUM, "title": "среднее"},
    "hard": {"xp": XP_HARD, "title": "сложное"},
}

# Источники прогресса: SQL считает значение метрики за всё время,
# прогресс = текущее значение минус базовое (снятое при выдаче квеста).
POOL: tuple[dict[str, Any], ...] = (
    {
        "key": "drops",
        "title": "Открой карту «Северо-Юг»",
        "sql": "select count(*) from drops where user_id = $1",
        "needs": {"light": (1, 2), "medium": (3, 5), "hard": (6,)},
    },
    {
        "key": "cases",
        "title": "Открой кейсы",
        "sql": "select count(*) from cases where user_id = $1 and opened",
        "needs": {"light": (1, 2), "medium": (3, 4), "hard": (6,)},
    },
    {
        "key": "upgrades",
        "title": "Крути апгрейдер",
        "sql": "select count(*) from upgrader_log where user_id = $1",
        "needs": {"light": (1, 2), "medium": (3, 5), "hard": (8,)},
    },
    {
        "key": "sold",
        "title": "Сдай карты скупщику",
        "sql": "select count(*) from buyer_log where user_id = $1",
        "needs": {"light": (1, 2), "medium": (3, 6), "hard": (10,)},
    },
    {
        "key": "casino",
        "title": "Сыграй в казино",
        "sql": "select count(*) from casino_log where user_id = $1",
        "needs": {"light": (1, 3), "medium": (5, 8), "hard": (12,)},
    },
    {
        "key": "shop",
        "title": "Купи что-нибудь в магазине",
        "sql": "select count(*) from shop_log where user_id = $1",
        "needs": {"light": (1,), "medium": (2, 3), "hard": (5,)},
    },
    {
        "key": "deals",
        "title": "Сделки на рынке",
        "sql": "select count(*) from history where buyer_id = $1 or seller_id = $1",
        "needs": {"light": (1,), "medium": (2, 3), "hard": (5,)},
    },
    {
        "key": "battles",
        "title": "Проведи PvP-бои",
        "sql": "select count(*) from battles where challenger_id = $1 or opponent_id = $1",
        "needs": {"light": (1, 2), "medium": (3, 5), "hard": (7,)},
    },
    {
        "key": "wins",
        "title": "Победи в PvP",
        "sql": "select wins from players where user_id = $1",
        "needs": {"light": (1,), "medium": (2, 3), "hard": (5,)},
    },
    {
        "key": "boss",
        "title": "Ударь рейд-босса",
        "sql": "select coalesce(sum(hits), 0) from boss_hits where user_id = $1",
        "needs": {"light": (3, 6), "medium": (10, 15), "hard": (25,)},
    },
    {
        "key": "gems",
        "title": "Найди кристаллы в подземелье",
        "sql": "select count(*) from gem_drops where user_id = $1",
        "needs": {"light": (1,), "medium": (2, 3), "hard": (5,)},
    },
    {
        "key": "gifts",
        "title": "Подари карту другу",
        "sql": "select count(*) from gifts where sender_id = $1",
        "needs": {"light": (1,), "medium": (2,), "hard": (4,)},
    },
)

BY_KEY = {item["key"]: item for item in POOL}
DEFAULT_LAYOUT = ("light", "light", "light", "medium", "medium", "medium", "hard")
PLUS_LAYOUT = ("light", "hard")


def _rng(season: str, day: date) -> random.Random:
    digest = hashlib.sha256(f"pass|{season}|{day.isoformat()}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def daily(season: str, day: date) -> list[dict[str, Any]]:
    """Семь основных квестов дня + два бонусных для сп+."""
    rng = _rng(season, day)
    picked: list[str] = []
    quests: list[dict[str, Any]] = []

    def take(tier: str, slot: int, plus: bool) -> None:
        pool = [item for item in POOL if item["key"] not in picked]
        if not pool:
            picked.clear()
            pool = list(POOL)
        item = rng.choice(pool)
        picked.append(item["key"])
        need = rng.choice(item["needs"][tier])
        quests.append(
            {
                "slot": slot,
                "key": item["key"],
                "tier": tier,
                "title": item["title"],
                "need": int(need),
                "sql": item["sql"],
                "xp": TIERS[tier]["xp"],
                "plus": plus,
            }
        )

    for slot, tier in enumerate(DEFAULT_LAYOUT):
        take(tier, slot, False)
    for extra, tier in enumerate(PLUS_LAYOUT):
        take(tier, len(DEFAULT_LAYOUT) + extra, True)
    return quests


def day_xp(quests: list[dict[str, Any]], with_plus: bool = False) -> int:
    return sum(
        int(quest["xp"])
        for quest in quests
        if with_plus or not quest.get("plus")
    )
