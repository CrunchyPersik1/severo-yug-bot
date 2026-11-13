"""МЕГАКВЕСТ недели: одна большая цель и крупная награда.

Живёт рядом с обычными заданиями, но считается не по суточным счётчикам,
а по недельному окну (понедельник, 07:00 UTC = 12:00 по ЕКБ). Цель и
награда детерминированы номером недели: у всех игроков одна и та же цель,
и она не меняется, сколько ни перезагружай страницу.
"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from . import bundles
from .cards import CARDS_BY_RARITY

RESET_WEEKDAY = 0        # понедельник
RESET_HOUR_UTC = 7       # 12:00 по ЕКБ

# Десять видов цели. SQL считает прогресс внутри недельного окна ($2 — начало).
QUESTS: dict[str, dict[str, Any]] = {
    "drops": {
        "title": "Выбей карты «Северо-Юг»",
        "sql": "select count(*) from drops where user_id = $1 and rolled_at >= $2",
        "needs": (40, 80, 150),
    },
    "upgrades": {
        "title": "Крути апгрейдер",
        "sql": "select count(*) from upgrader_log where user_id = $1 and created_at >= $2",
        "needs": (15, 30, 60),
    },
    "sold": {
        "title": "Сдай карты скупщику",
        "sql": "select count(*) from buyer_log where user_id = $1 and created_at >= $2",
        "needs": (25, 50, 100),
    },
    "casino": {
        "title": "Сыграй в казино",
        "sql": "select count(*) from casino_log where user_id = $1 and created_at >= $2",
        "needs": (40, 80, 150),
    },
    "deals": {
        "title": "Заключи сделки на рынке",
        "sql": "select count(*) from history where (buyer_id = $1 or seller_id = $1) "
               "and timestamp >= $2",
        "needs": (8, 15, 30),
    },
    "shop": {
        "title": "Купи что-нибудь в магазине",
        "sql": "select count(*) from shop_log where user_id = $1 and created_at >= $2",
        "needs": (6, 12, 25),
    },
    "cases": {
        "title": "Открой кейсы",
        "sql": "select count(*) from cases where user_id = $1 and opened "
               "and created_at >= $2",
        "needs": (15, 30, 60),
    },
    "battles": {
        "title": "Проведи бои PvP",
        "sql": "select count(*) from battles where (challenger_id = $1 or opponent_id = $1) "
               "and created_at >= $2",
        "needs": (10, 20, 40),
    },
    "boss": {
        "title": "Бей рейд-босса",
        "sql": "select coalesce(sum(hits), 0) from boss_hits "
               "where user_id = $1 and updated_at >= $2",
        "needs": (20, 40, 80),
    },
    "gems": {
        "title": "Найди кристаллы в подземелье",
        "sql": "select count(*) from gem_drops where user_id = $1 and created_at >= $2",
        "needs": (3, 6, 12),
    },
}

ORDER: tuple[str, ...] = tuple(QUESTS)


def week_start(moment: datetime | None = None) -> datetime:
    """Начало текущей недели: понедельник, 07:00 UTC."""
    moment = moment or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    shifted = moment - timedelta(
        days=(moment.weekday() - RESET_WEEKDAY) % 7,
        hours=RESET_HOUR_UTC,
    )
    return shifted.replace(hour=RESET_HOUR_UTC, minute=0, second=0, microsecond=0)


def week_key(moment: datetime | None = None) -> str:
    start = week_start(moment)
    year, week, _ = start.isocalendar()
    return f"{year}-W{week:02d}"


def _rng(key: str) -> random.Random:
    digest = hashlib.sha256(f"mega|{key}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


REWARD_POOL: tuple[dict[str, Any], ...] = (
    {"title": "30 кристаллов", "bundle": {"gems": 30}},
    {"title": "8 кейсов 7Г", "bundle": {"cases_g": 8}},
    {"title": "150 000 очков", "bundle": {"points": 150_000}},
    {"title": "3 кейса «Ультра»", "bundle": {"cases_ultra": 3}},
    {"title": "500 акций биржи", "bundle": {"shares": 500}},
    {"title": "ультралегендарная карта", "bundle": {"cards": ["valeriya"]}},
    {"title": "60 кейсов 7Г", "bundle": {"cases_g": 60}},
    {"title": "500 000 очков", "bundle": {"points": 500_000}},
    {"title": "25 кристаллов и 5 кейсов 7Г", "bundle": {"gems": 25, "cases_g": 5}},
    {"title": "VIP на 14 дней и 5 кейсов 7Г", "bundle": {"vip_days": 14, "cases_g": 5}},
)


def quest(moment: datetime | None = None) -> dict[str, Any]:
    """Цель и награда этой недели — одинаковые для всех."""
    key = week_key(moment)
    rng = _rng(key)
    quest_key = rng.choice(list(ORDER))
    need = rng.choice(list(QUESTS[quest_key]["needs"]))
    reward = rng.choice(list(REWARD_POOL))
    bundle = bundles.make(**reward["bundle"])
    return {
        "week": key,
        "key": quest_key,
        "title": QUESTS[quest_key]["title"],
        "need": int(need),
        "sql": QUESTS[quest_key]["sql"],
        "reward": bundle,
        "reward_title": reward["title"],
        "reward_text": bundles.text(bundle),
        "ends_at": (week_start(moment) + timedelta(days=7)).isoformat(),
    }
