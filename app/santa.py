"""Ивент «Санта Егор»: роадмап, сюжетка и магазин с ротацией.

Санта открывает магазин только после того, как игрок прошёл сюжетку с
эльфами. Дальше магазин живёт циклами: N дней открыт, M дней Санты нет.
Сколько дней и с какой наценкой — зависит от того, какое решение выбрал
игрок в разговоре.
"""

from __future__ import annotations

import hashlib
import random
from datetime import date, datetime, timedelta, timezone
from typing import Any

from . import eggs as eggs_mod
from . import pets

EPOCH = date(2026, 11, 14)   # сегодняшний день по ЕКБ
EKB = timezone(timedelta(hours=5))

LEVELS_TOTAL = 6


def today_ekb(moment: datetime | None = None) -> date:
    moment = moment or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(EKB).date()


# --------------------------------------------------------------------------- #
# Сюжет: четыре решения, каждое меняет поведение Санты.
# --------------------------------------------------------------------------- #

CHOICES: tuple[dict[str, Any], ...] = (
    {
        "id": "praise",
        "title": "Попросить Санту быть добрее к эльфам",
        "note": "хороший финал: скидки и частые визиты",
        "discount": 0.15,
        "on_days": 4,
        "off_days": 3,
        "story": "Эльфы получают тепло, Санта доволен собой и тобой.",
    },
    {
        "id": "gifts",
        "title": "Устроить эльфам праздник",
        "note": "средний финал: небольшая скидка",
        "discount": 0.07,
        "on_days": 3,
        "off_days": 4,
        "story": "Эльфы довольны подарками, но дисциплина осталась.",
    },
    {
        "id": "rules",
        "title": "Оставить всё как есть",
        "note": "нейтрально: без скидок и наценок",
        "discount": 0.0,
        "on_days": 2,
        "off_days": 5,
        "story": "Ты не стал менять уклад Санты. Эльфы всё ещё ворчат.",
    },
    {
        "id": "strict",
        "title": "Поддержать строгость Санты",
        "note": "плохой финал: наценка и редкие визиты",
        "discount": -0.10,
        "on_days": 1,
        "off_days": 6,
        "story": "Эльфы обиделись сильнее. Санта хмурится.",
    },
)

CHOICE_BY_ID: dict[str, dict[str, Any]] = {item["id"]: item for item in CHOICES}


def choice(choice_id: str | None) -> dict[str, Any] | None:
    return CHOICE_BY_ID.get(str(choice_id or ""))


def is_good(choice_id: str | None) -> bool:
    picked = choice(choice_id)
    return bool(picked and picked["discount"] > 0)


# --------------------------------------------------------------------------- #
# Эльфы: шесть уровней. Бой идёт как в подземелье — один моб с приёмами.
# --------------------------------------------------------------------------- #

ELVES: tuple[dict[str, Any], ...] = (
    {"level": 1, "name": "Амир-разведчик", "hp": 260, "dmg": 12,
     "speed": 0.9, "aim": 0.45, "dash": 0.30,
     "reward": {"eggs": 1}},
    {"level": 2, "name": "Амир-лучник", "hp": 380, "dmg": 16,
     "speed": 1.0, "aim": 0.55, "dash": 0.35,
     "reward": {"eggs": 1}},
    {"level": 3, "name": "Амир-стрелок", "hp": 520, "dmg": 21,
     "speed": 1.1, "aim": 0.65, "dash": 0.40,
     "reward": {"eggs": 1, "gems": 10}},
    {"level": 4, "name": "Амир-ветеран", "hp": 700, "dmg": 27,
     "speed": 1.2, "aim": 0.7, "dash": 0.5,
     "reward": {"eggs": 2, "gems": 15}},
    {"level": 5, "name": "Амир-мастер", "hp": 950, "dmg": 34,
     "speed": 1.3, "aim": 0.75, "dash": 0.55,
     "reward": {"gems": 20}},
    {"level": 6, "name": "Амир-полководец", "hp": 1400, "dmg": 45,
     "speed": 1.4, "aim": 0.8, "dash": 0.6,
     "reward": {"eggs": 5, "gems": 50}},
)


def level(number: int) -> dict[str, Any] | None:
    for item in ELVES:
        if int(item["level"]) == int(number):
            return dict(item)
    return None


def levels() -> list[dict[str, Any]]:
    return [dict(item) for item in ELVES]


# --------------------------------------------------------------------------- #
# Магазин: 5 петов и яйцо, ротация по 7-дневным циклам.
# --------------------------------------------------------------------------- #

SHOP_PETS = 5


def cycle_day(day: date, choice_id: str | None = None) -> int:
    """День внутри цикла (0..N) и длина цикла — по выбору игрока."""
    picked = choice(choice_id) or CHOICE_BY_ID["rules"]
    on, off = int(picked["on_days"]), int(picked["off_days"])
    length = on + off
    offset = (day - EPOCH).days % length
    return offset if 0 <= offset < on else -1


def shop_open(day: date, choice_id: str | None = None) -> bool:
    return cycle_day(day, choice_id) >= 0


def opens_in_days(day: date, choice_id: str | None = None) -> int:
    picked = choice(choice_id) or CHOICE_BY_ID["rules"]
    length = int(picked["on_days"]) + int(picked["off_days"])
    offset = (day - EPOCH).days % length
    if offset < int(picked["on_days"]):
        return 0
    return length - offset


def season(day: date, choice_id: str | None = None) -> int:
    """Номер открытого периода: по нему стабилен сток."""
    picked = choice(choice_id) or CHOICE_BY_ID["rules"]
    length = int(picked["on_days"]) + int(picked["off_days"])
    return (day - EPOCH).days // length


def _rng(*parts: Any) -> random.Random:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def stock(day: date, choice_id: str | None = None) -> list[dict[str, Any]]:
    """Шесть товаров: пять петов и яйцо. Цены зависят от решения."""
    picked = choice(choice_id) or CHOICE_BY_ID["rules"]
    # discount > 0 — скидка, discount < 0 — наценка
    factor = 1.0 - float(picked["discount"])
    rng = _rng("santa", season(day, choice_id))
    pool = [pet for pet in pets.PETS if pet.price > 0]
    picks = rng.sample(pool, k=min(SHOP_PETS, len(pool)))
    items: list[dict[str, Any]] = []
    for pet in picks:
        price = max(1, int(round(pet.price * factor)))
        items.append(
            {
                "kind": "pet",
                "id": pet.id,
                "title": pet.name,
                "emoji": pet.emoji,
                "note": pet.title + " · " + pet.note,
                "price": price,
                "currency": pet.currency,
                "rare": pet.rare,
            }
        )
    egg = eggs_mod.egg()
    items.append(
        {
            "kind": "egg",
            "id": egg["id"],
            "title": egg["title"],
            "emoji": "🥚",
            "note": egg["note"],
            "price": max(1, int(round(egg["price"] * factor))),
            "currency": egg["currency"],
            "rare": False,
        }
    )
    return items


def find_item(day: date, choice_id: str | None, item_id: str) -> dict[str, Any] | None:
    for item in stock(day, choice_id):
        if item["id"] == item_id and item["kind"] in ("pet", "egg"):
            return item
    return None


def payload(day: date, choice_id: str | None) -> dict[str, Any]:
    return {
        "day": day.isoformat(),
        "open": shop_open(day, choice_id),
        "opens_in_days": opens_in_days(day, choice_id),
        "season": season(day, choice_id),
        "stock": stock(day, choice_id),
        "discount": (choice(choice_id) or {}).get("discount", 0.0),
    }
