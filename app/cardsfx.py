"""Визуальный отклик карточки: насколько «богато» она выглядит при открытии.

Одна карта — один уровень 0..5. Уровень задаёт и анимацию раскрытия
(вспышка, лучи, тряска), и постоянное оформление (рамка, декор поверх
шапки карты). Логика живёт здесь, а не в разметке: страницы только читают
payload и рисуют классы fx-l0 … fx-l5.

Правила простые: чем реже карта, тем дороже отклик. Обычная — просто
картинка, ультра — весь экран в эффектах.
"""

from __future__ import annotations

from .cards import RARITIES

# Уровень отклика по редкости. 0 — без эффектов, 5 — «экран в огне».
FX_LEVELS: dict[str, int] = {
    "rare": 0,
    "superrare": 0,
    "epic": 1,
    "mythic": 1,
    "legendary": 2,
    "secret": 3,
    "ultimate": 4,
    "ultra": 5,
    "teacher": 5,
    "premium": 5,
}

# Цвет рамки и свечения: берём из палитры лент, чтобы карточка в коллекции
# и та же карточка в ленте кейса выглядели одинаково.
FX_COLORS: dict[str, str] = {
    "rare": "#94a3b8",
    "superrare": "#3b82f6",
    "epic": "#a855f7",
    "mythic": "#ef4444",
    "legendary": "#eab308",
    "secret": "#64748b",
    "ultimate": "#e879f9",
    "ultra": "#22d3ee",
    "teacher": "#a16207",
    "premium": "#ffd166",
}

# Что рисуется поверх шапки карты. Список — не случайный набор: каждый
# элемент имеет свой слой эффектов в CSS страниц.
DECOR: dict[int, tuple[str, ...]] = {
    0: (),
    1: ("glow",),
    2: ("glow", "sparks"),
    3: ("glow", "sparks", "veil"),
    4: ("glow", "sparks", "rune", "shine"),
    5: ("glow", "sparks", "rays", "crown", "halo", "shine"),
}

# Как долго играть раскрытие (мс). Страницы берут отсюда, чтобы анимация
# на всех экранах шла одинаково.
REVEAL_MS: dict[int, int] = {0: 0, 1: 420, 2: 620, 3: 780, 4: 980, 5: 1300}

MAX_LEVEL = 5


def level(rarity: str) -> int:
    """Уровень отклика для редкости. Неизвестная редкость — как обычная."""
    return int(FX_LEVELS.get(str(rarity), 0))


def color(rarity: str) -> str:
    return FX_COLORS.get(str(rarity), "#334155")


def decor(rarity: str) -> list[str]:
    return list(DECOR.get(level(rarity), ()))


def reveal_ms(rarity: str) -> int:
    return int(REVEAL_MS.get(level(rarity), 0))


def payload(rarity: str) -> dict[str, object]:
    """Всё, что нужно странице, чтобы отрисовать карточку."""
    lvl = level(rarity)
    return {
        "level": lvl,
        "color": color(rarity),
        "decor": decor(rarity),
        "reveal_ms": reveal_ms(rarity),
        "title": RARITIES[rarity].name if rarity in RARITIES else "",
        "emoji": RARITIES[rarity].emoji if rarity in RARITIES else "",
    }


def fullscreen(rarity: str) -> bool:
    """Гаснет ли весь экран при раскрытии (лучи, тряска, вспышка)."""
    return level(rarity) >= 4
