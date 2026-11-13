"""Скорость открытия призов: от «супер быстрой» до «черепахи».

Чем медленнее, тем дольше лента/колесо ползёт в конце: последние полтора
тайла оно доползает отдельным медленным шагом, поэтому игрок до последнего
не понимает, что выпало. Это и есть азарт — не «мгновенный результат».

Значение хранится в настройках игрока (`speed`), страницы берут готовые
миллисекунды из /api/case и /api/roulette.
"""

from __future__ import annotations

DEFAULT = "slow"

# id, подпись, лента (мс), колесо (мс)
SPEEDS: tuple[dict[str, object], ...] = (
    {"id": "turbo", "title": "Супер быстрая", "reel_ms": 2200, "wheel_ms": 3000},
    {"id": "fast", "title": "Быстрая", "reel_ms": 3200, "wheel_ms": 4200},
    {"id": "normal", "title": "Медленнее", "reel_ms": 4800, "wheel_ms": 6000},
    {"id": "slow", "title": "Медленная", "reel_ms": 6800, "wheel_ms": 8200},
    {"id": "turtle", "title": "Черепаха", "reel_ms": 9500, "wheel_ms": 11000},
)

BY_ID: dict[str, dict[str, object]] = {str(item["id"]): item for item in SPEEDS}

# Пачка (2-10 призов) не должна тянуться вечность: режем время, но не
# ниже «быстрой».
MIN_BATCH_MS = 2400
BATCH_FACTOR = 0.6

# Сколько держать финальный кадр перед показом текста результата.
HOLD_MS = 450


def is_speed(value: object) -> bool:
    return str(value or "") in BY_ID


def normalize(value: object) -> str:
    value = str(value or "")
    return value if value in BY_ID else DEFAULT


def reel_ms(value: object, count: int = 1) -> int:
    speed = BY_ID[normalize(value)]
    ms = int(speed["reel_ms"])
    if int(count) > 1:
        ms = max(MIN_BATCH_MS, int(ms * BATCH_FACTOR))
    return ms


def wheel_ms(value: object) -> int:
    return int(BY_ID[normalize(value)]["wheel_ms"])


def hold_ms() -> int:
    return HOLD_MS


def payload() -> list[dict[str, object]]:
    """Список скоростей для кнопок в настройках."""
    return [
        {"id": item["id"], "title": item["title"], "reel_ms": item["reel_ms"]}
        for item in SPEEDS
    ]
