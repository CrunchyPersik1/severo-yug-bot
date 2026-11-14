"""Лавка Насибуллина: ежедневный сток оружия за монеты подземелья.

Ассортимент детерминирован по дате (ЕКБ): в один день у всех одинаковый,
на следующий — новый. Ничего не хранится, кроме отметок о покупках.
"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone
from typing import Any

EKB = timezone(timedelta(hours=5))
STOCK_SIZE = 6
KINDS = ("sword", "bow", "staff")
KIND_NAMES = {"sword": "клинок", "bow": "лук", "staff": "посох"}
RARITIES = (
    ("обычное", 1.00, 0.45),
    ("редкое", 1.35, 0.28),
    ("эпическое", 1.80, 0.16),
    ("легендарное", 2.40, 0.08),
    ("мифическое", 3.20, 0.03),
)
TIER_NAMES = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X")


def day_key(now: datetime | None = None):
    return (now or datetime.now(EKB)).date()


def tier_cap(level: int) -> int:
    """До какого тира можно докупиться: новичку не продаём топ-стволы."""
    return max(0, min(9, int(level) // 8))


def stock(day=None, level: int = 1) -> list[dict[str, Any]]:
    """Шесть оружий на день: вид, тир, редкость, статы и цена в монетах."""
    from . import dungeon as dungeon_mod

    cap = tier_cap(level)
    day = day or day_key()
    seed = int(hashlib.sha256(f"nasibullin:{day.isoformat()}".encode()).hexdigest()[:12], 16)
    rng = random.Random(seed)
    out: list[dict[str, Any]] = []
    used: set[str] = set()
    weights = [w for _, _, w in RARITIES]
    while len(out) < STOCK_SIZE:
        kind = rng.choice(KINDS)
        tier = rng.randrange(0, cap + 1)
        variant = rng.randrange(0, 6)
        weapon_id = f"{kind}_{tier}_{variant}"
        if weapon_id in used:
            continue
        used.add(weapon_id)
        rarity, mult, _ = rng.choices(RARITIES, weights=weights, k=1)[0]
        price = int(round((240 + tier * 320) * mult * 0.75))
        rank_dmg = dungeon_mod.WEAPON_RANK_DMG[tier]
        rank_step = dungeon_mod.WEAPON_RANK_STEP[tier]
        out.append(
            {
                "id": weapon_id,
                "dmg": rank_dmg + variant * rank_step,
                "range": 60 + tier * 9 + variant * 3,
                "spd": round(1.15 - tier * 0.03 - variant * 0.01, 3),
                "kind": kind,
                "tier": tier,
                "rarity": rarity,
                "price": price,
                "name": f"{KIND_NAMES[kind].capitalize()} {TIER_NAMES[tier]} · {rarity}",
            }
        )
    out.sort(key=lambda w: w["price"])
    return out


def find(weapon_id: str, day=None, level: int = 99) -> dict[str, Any] | None:
    for item in stock(day, level):
        if item["id"] == weapon_id:
            return item
    return None


def payload(coins: int, bought: list[str], day=None, level: int = 1) -> dict[str, Any]:
    day = day or day_key()
    items = stock(day, level)
    for item in items:
        item["bought"] = item["id"] in bought
    return {
        "day": day.isoformat(),
        "stock": items,
        "coins": int(coins),
        "shows_in": 1,
    }
