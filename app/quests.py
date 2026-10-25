"""Квесты на странице «Задания»: список и одноразовая награда.

Прогресс считается по тем же счётчикам, что и недельный ивент
(event_week.SOURCES) — ничего не перехватываем в обработчиках, поэтому
квесты не могут сломать игру. А вот награда тут своя и у каждого квеста
разная: кейсы, очки, крутки рулетки, дропы и Юги — чтобы не было семи
одинаковых «+очки и кейс».
"""

from __future__ import annotations

from . import event_week

# Награды по ключу квеста. Ключи — те же, что в event_week.SOURCES.
REWARDS: dict[str, dict] = {
    # выбить карты — премия кейсами
    "drops": {"cases": 2},
    # апгрейды в апгрейдере — очки
    "upgrades": {"points": 20_000},
    # скупщик — крутки рулетки и кейс
    "sold": {"roulette": 2, "cases": 1},
    # казино — очки и кейс
    "casino": {"points": 25_000, "cases": 1},
    # сделки на рынке — Юги в кликер
    "deals": {"yugi": 500},
    # магазин — дропы карт
    "shop": {"drops": 3},
    # кликер — премия кейсами
    "taps": {"cases": 3},
}

POINTS = 15_000        # запасная награда, если ключ новый и правила нет


def order() -> tuple[str, ...]:
    return tuple(event_week.ORDER)


def reward_for(index_or_key: object) -> dict:
    """Награда за квест: принимает и номер в списке, и ключ."""
    if isinstance(index_or_key, str):
        return dict(REWARDS.get(index_or_key) or {"points": POINTS})
    names = order()
    index = int(index_or_key)  # type: ignore[arg-type]
    if 0 <= index < len(names):
        return dict(REWARDS.get(names[index]) or {"points": POINTS})
    return {"points": POINTS}


def _plural(number: int, one: str, few: str, many: str) -> str:
    if number % 10 == 1 and number % 100 != 11:
        return one
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return few
    return many


def reward_text(reward: dict) -> str:
    parts: list[str] = []
    if reward.get("points"):
        number = "%d" % int(reward["points"])
        groups = []
        while len(number) > 3:
            groups.insert(0, number[-3:])
            number = number[:-3]
        groups.insert(0, number)
        parts.append(" ".join(groups) + " очков")
    if reward.get("cases"):
        count = int(reward["cases"])
        parts.append("%d %s" % (count, _plural(count, "кейс", "кейса", "кейсов")))
    if reward.get("roulette"):
        count = int(reward["roulette"])
        parts.append("%d %s" % (count, _plural(count, "крутка", "крутки", "круток")))
    if reward.get("drops"):
        count = int(reward["drops"])
        parts.append("%d %s" % (count, _plural(count, "дроп", "дропа", "дропов")))
    if reward.get("yugi"):
        parts.append("%d Югов" % int(reward["yugi"]))
    return " + ".join(parts) or "награда"


def need_for(key: str) -> int:
    return event_week.need_for(key, 1)


def title_for(key: str) -> str:
    return event_week.TITLES.get(key, key)


def source_sql(key: str) -> str | None:
    return event_week.SOURCES.get(key)
