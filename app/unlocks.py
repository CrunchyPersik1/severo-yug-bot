
"""Условия открытия коллекции 7Д: уровень 50 и исторический пик 1 000 000.

7Д — вторая коллекция с дорогими картами и кейсом. Раньше её мог открыть
любой новичок, и это ломало экономику: за пару минут реально было вынести
сотни тысяч очков. Теперь нужен и уровень, и «заслуга» — когда-то на
балансе было хотя бы миллион.
"""

from __future__ import annotations

from typing import Any

D7_LEVEL = 50
D7_PEAK = 1_000_000


def level_of(xp: int) -> int:
    from . import levels as levels_mod

    return int(levels_mod.level_from_xp(int(xp or 0)))


def check(level: int, peak: int) -> dict[str, Any]:
    """Открыта ли 7Д и чего не хватает."""
    open_ = level >= D7_LEVEL and peak >= D7_PEAK
    return {
        "open": open_,
        "level": int(level),
        "need_level": D7_LEVEL,
        "peak": int(peak),
        "need_peak": D7_PEAK,
        "level_ok": level >= D7_LEVEL,
        "peak_ok": peak >= D7_PEAK,
    }


def reason(status: dict[str, Any]) -> str:
    """Человеческая причина блокировки."""
    if status["open"]:
        return ""
    if not status["level_ok"] and not status["peak_ok"]:
        return (
            f"Западо-Восток открывается с {D7_LEVEL} уровня и когда на балансе "
            f"хотя бы раз было {D7_PEAK:,} очков".replace(",", " ")
        )
    if not status["level_ok"]:
        return f"До Западо-Востока нужен {D7_LEVEL} уровень (сейчас {status['level']})"
    return (
        f"Нужно, чтобы на балансе хотя бы раз было {D7_PEAK:,} очков".replace(",", " ")
    )
