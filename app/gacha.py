"""Выпадение карт («Северо-Юг»).

Сначала по весам выбирается редкость, затем карта равномерно внутри редкости.
Лимит — 1 раз в сутки на пользователя (глобально, не на чат).
Сброс в 12:00 по ЕКБ (UTC+5) = 07:00 UTC.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

from .cards import CARDS_BY_RARITY, RARITIES, SECRET_CARD_IDS, Card

RESET_HOUR_UTC = 7  # 12:00 по ЕКБ

# Сколько карт в сутки можно получить по умолчанию.
DROPS_PER_DAY = 1


def day_key(moment: datetime | None = None) -> date:
    """Игровые сутки: сутки начинаются в 07:00 UTC, а не в 00:00."""
    moment = moment or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (moment.astimezone(timezone.utc) - timedelta(hours=RESET_HOUR_UTC)).date()


def next_reset(moment: datetime | None = None) -> datetime:
    """Момент следующего сброса лимита (07:00 UTC)."""
    moment = moment or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    candidate = moment.replace(hour=RESET_HOUR_UTC, minute=0, second=0, microsecond=0)
    if candidate <= moment:
        candidate += timedelta(days=1)
    return candidate


def roll_rarity(rng: random.Random | None = None) -> str:
    rng = rng or random
    keys = list(RARITIES)
    weights = [RARITIES[key].weight for key in keys]
    return rng.choices(keys, weights=weights, k=1)[0]


def roll_card(rng: random.Random | None = None) -> Card:
    rng = rng or random
    rarity = roll_rarity(rng)
    pool = [
        card
        for card in CARDS_BY_RARITY[rarity]
        if card.card_id not in SECRET_CARD_IDS
    ]
    return rng.choice(pool or CARDS_BY_RARITY[rarity])


def rarity_weights_table() -> list[tuple[str, str, float, int]]:
    """(ключ, название, вес, число карт) — для проверок и /info."""
    return [
        (key, RARITIES[key].name, RARITIES[key].weight, len(CARDS_BY_RARITY[key]))
        for key in RARITIES
    ]
