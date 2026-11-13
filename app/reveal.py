"""Открытие приза: 15 секунд с постепенным замедлением.

Скоростей больше нет — есть один честно долгий прокрут. Лента и колесо
идут тремя стадиями: быстро, медленнее, совсем медленно. В самом конце
есть шанс, что приз «проскочит» ещё на один тайл: тогда игрок видит, как
лента почти встала и всё-таки проехала дальше.

Важно: визуальный финиш всегда совпадает с призом, который выдал сервер.
«Проскок» не подменяет награду — он только делает остановку неочевидной.
"""

from __future__ import annotations

# Минимальная длина прокрута. Меньше не бывает ни в каком профиле.
SPIN_MS = 15_000

# Доли времени на три стадии: разгон, замедление, доползание.
STAGE_SHARE = (0.45, 0.40, 0.15)

# Шанс, что в конце лента проедет ещё один тайл.
SLIP_CHANCE = 0.15

# Сколько тайлов проходит каждая стадия. Обычно в конце лента просто
# «досаживается» меньше чем на полтайла — кажется, что встала на месте.
STAGE_TILES = (14.0, 4.0, 0.45)

# С шансом SLIP_CHANCE последняя стадия — целый тайл: видно, как лента
# проехала ещё и встала на соседнюю награду.
SLIP_TILES = (14.0, 2.9, 1.7)


def stage_ms(total: int = SPIN_MS) -> tuple[int, int, int]:
    """Миллисекунды трёх стадий."""
    total = max(SPIN_MS, int(total))
    first = int(round(total * STAGE_SHARE[0]))
    second = int(round(total * STAGE_SHARE[1]))
    return first, second, total - first - second


def total_ms() -> int:
    return SPIN_MS


def slip_chance() -> float:
    return SLIP_CHANCE


def payload() -> dict[str, object]:
    """Всё, что нужно страницам для анимации."""
    first, second, third = stage_ms()
    return {
        "spin_ms": SPIN_MS,
        "spin_stages": [first, second, third],
        "slip_chance": SLIP_CHANCE,
        "stage_tiles": list(STAGE_TILES),
        "slip_tiles": list(SLIP_TILES),
    }
