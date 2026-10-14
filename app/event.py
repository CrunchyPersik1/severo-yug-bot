"""Ивент: бусты шансов и кликер-копилка.

Шансы поднимаются ТОЛЬКО в «Северо-Юг» и рулетке. Кейсы и казино не трогаем.

Награды копилки не выдаются сразу — они лежат до конца ивента, и админ
раздаёт их одной транзакцией, когда выключает ивент.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

# Во сколько раз щедрее становится дроп во время ивента.
EVENT_BOOST = 3.0

# Счастливая минута: разброс от «слегка» до «совсем имба»
MINUTE_MIN = 1.5
MINUTE_MAX = 60.0
MINUTE_SECONDS = 60

# Сколько очков падает в копилку за один клик.
CLICK_POINTS = 50


@dataclass(frozen=True)
class EventState:
    active: bool
    clicker: bool
    happy_until: datetime | None
    happy_boost: float
    started_at: datetime | None


async def state(db: Any) -> EventState:
    row = await db.event_row()
    return EventState(
        active=bool(row["active"]),
        clicker=bool(row["clicker"]),
        happy_until=row["happy_until"],
        happy_boost=float(row["happy_boost"] or 1.0),
        started_at=row["started_at"],
    )


def boost(st: EventState, moment: datetime | None = None) -> float:
    """Текущий множитель шансов. 1.0 — обычная жизнь."""
    value = 1.0
    if st.active:
        value *= EVENT_BOOST
    now = moment or datetime.now(timezone.utc)
    if st.happy_until is not None and st.happy_until > now:
        value *= st.happy_boost
    return value


async def drop_boost(db: Any) -> float:
    return boost(await state(db))


def happy_left(st: EventState, moment: datetime | None = None) -> int:
    if st.happy_until is None:
        return 0
    now = moment or datetime.now(timezone.utc)
    return max(0, int((st.happy_until - now).total_seconds()))


def roll_happy_boost(rng: random.Random | None = None) -> float:
    rng = rng or random
    return round(rng.uniform(MINUTE_MIN, MINUTE_MAX), 2)


def describe_boost(value: float) -> str:
    if value >= 20:
        return "это полный имбаланс 🔥"
    if value >= 8:
        return "очень щедро"
    if value >= 3:
        return "заметно щедрее"
    return "по мелочи"


def happy_until(moment: datetime | None = None) -> datetime:
    return (moment or datetime.now(timezone.utc)) + timedelta(seconds=MINUTE_SECONDS)
