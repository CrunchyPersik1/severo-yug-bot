"""Квесты на странице «Задания»: список и одноразовая награда.

Прогресс считается по тем же счётчикам, что и недельный ивент
(event_week.SOURCES) — ничего не перехватываем в обработчиках, поэтому
квесты не могут сломать игру. А вот награда тут своя: забрал один раз
и всё, в отличие от ежедневного ивента.
"""

from __future__ import annotations

from . import event_week

POINTS = 15_000        # очков за квест
CASE_EVERY = 2         # каждый второй квест ещё и кейс


def order() -> tuple[str, ...]:
    return tuple(event_week.ORDER)


def reward_for(index: int) -> dict:
    """Награда за квест по его номеру в списке."""
    reward: dict = {"points": POINTS}
    if index % CASE_EVERY == 1:
        reward["cases"] = 1
    return reward


def reward_text(reward: dict) -> str:
    return event_week.reward_text(reward)


def need_for(key: str) -> int:
    return event_week.need_for(key, 1)


def title_for(key: str) -> str:
    return event_week.TITLES.get(key, key)


def source_sql(key: str) -> str | None:
    return event_week.SOURCES.get(key)
