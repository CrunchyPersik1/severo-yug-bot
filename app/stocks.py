"""Биржа «Северо-Юг»: акции с живым курсом.

Курс общий для всех и двигается шагами раз в TICK_SECONDS. Шаг — симметричный
случайный (без дрейфа), то есть в среднем курс стоит на месте: поднять очки
можно только на реальном росте. Плюс комиссия на вход и выход — она делает
быстрый трейд убыточным, поэтому фармить очки на бирже нельзя.
"""

from __future__ import annotations

import random

TICK_SECONDS = 15
# Если сервис спал, догоняем курс, но не больше этого числа шагов за раз.
MAX_CATCHUP_TICKS = 8

# Комиссия: покупаем дороже курса, продаём дешевле. 3% в каждую сторону.
FEE = 0.03

# Границы, чтобы курс не улетел в ноль или в космос.
FLOOR_MULT = 0.40
CEIL_MULT = 2.20

# Возврат к базе. Без него курс уходил в пол или потолок и залипал там
# навсегда: цены «скатывались» и больше не двигались.
REVERT = 0.05

# Потолок на одну компанию: больше 100 монет держать нельзя.
MAX_PER_STOCK = 100

# Плавный подход к цели, которую задаёт админ: за шаг проходим долю разрыва,
# но не больше TARGET_MAX_STEP от текущей цены (без телепорта).
TARGET_PULL = 0.6
TARGET_MAX_STEP = 0.25

# Оповещение о росте: срабатывает, когда курс поднялся на 10% от прошлой отметки.
ALERT_THRESHOLD = 0.10
# Но не чаще, чем раз в 15 минут на монету — чтобы не спамить.
ALERT_COOLDOWN_MINUTES = 15

# Скачок курса за один шаг: с этого момента ставим отметку на графике.
SPIKE_THRESHOLD = 0.05

STOCKS: tuple[dict[str, object], ...] = (
    {"slug": "syug", "name": "SeveroCoin", "emoji": "🎴", "base": 1000, "vol": 0.030},
    {"slug": "uchitel", "name": "ДэнКоин", "emoji": "🪙", "base": 2500, "vol": 0.022},
    {"slug": "misha", "name": "Миша Inc.", "emoji": "🥔", "base": 1500, "vol": 0.040},
    {"slug": "ludoman", "name": "MusorDelta_Coin", "emoji": "🗑️", "base": 800, "vol": 0.050},
    {"slug": "kartofan", "name": "Карточный_Coin", "emoji": "🃏", "base": 600, "vol": 0.035},
    {"slug": "zeya", "name": "ЗеяКоин", "emoji": "🌌", "base": 1200, "vol": 0.028},
)


def by_slug(slug: str) -> dict[str, object] | None:
    clean = (slug or "").strip().lower()
    for stock in STOCKS:
        if stock["slug"] == clean:
            return stock
    return None


def buy_price(price: int) -> int:
    """Сколько стоит одна акция при покупке (с комиссией)."""
    return max(1, round(int(price) * (1 + FEE)))


def sell_price(price: int) -> int:
    """Сколько дадут за одну акцию при продаже (за вычетом комиссии)."""
    return max(1, round(int(price) * (1 - FEE)))


def clamp_target(target: int, base: int) -> int:
    """Приводит цель к рабочему коридору.

    Цель могла устареть: пол подняли, а цель осталась ниже. Тогда цена
    упиралась в пол, а сравнение «дошли ли до цели» шло с несжатой целью —
    она никогда не считалась достигнутой, и курс залипал навсегда.
    """
    low = int(int(base) * FLOOR_MULT)
    high = int(int(base) * CEIL_MULT)
    return max(low, min(high, int(target)))


def next_price(
    price: int,
    base: int,
    volatility: float,
    rng: random.Random | None = None,
    target: int | None = None,
) -> int:
    """Один шаг курса.

    Если задана цель (её ставит админ), плавно идём к ней: за шаг проходим
    долю разрыва, но не больше TARGET_MAX_STEP — быстро, но без прыжка.
    Иначе — обычный симметричный случайный шаг в коридоре.
    """
    price = int(price)
    low = int(int(base) * FLOOR_MULT)
    high = int(int(base) * CEIL_MULT)
    if target is not None and int(target) > 0:
        # Цель тоже держим в коридоре: иначе курс улетал за границы, а график
        # и проценты потом врали.
        target = clamp_target(target, base)
        if price == target:
            return target
        step = round((target - price) * TARGET_PULL)
        limit = max(1, round(price * TARGET_MAX_STEP))
        step = max(-limit, min(limit, step))
        if step == 0:
            step = 1 if target > price else -1
        new = price + step
        if (target - price) * (target - new) <= 0:
            return target
        return int(max(low, min(high, new)))

    rng = rng or random
    # Тянем курс к базе: чем дальше ушёл, тем сильнее тянет обратно.
    drift = ((float(base) - float(price)) / float(base)) * REVERT
    change = rng.uniform(-float(volatility), float(volatility)) + drift
    value = price * (1.0 + change)
    new = int(max(low, min(high, round(value))))
    if new == price and abs(drift) > 0.0005:
        # На дешёвых курсах шаг округлялся в ноль и монета замирала.
        new = price + (1 if drift > 0 else -1)
    return int(max(low, min(high, new)))


def alert_due(
    price: int,
    alert_price: int,
    seconds_since_alert: float | None = None,
) -> bool:
    """Пора ли сообщать о росте. Отметка поднимается вместе с курсом."""
    if alert_price <= 0:
        return False
    if price < alert_price * (1 + ALERT_THRESHOLD):
        return False
    if (
        seconds_since_alert is not None
        and seconds_since_alert < ALERT_COOLDOWN_MINUTES * 60
    ):
        return False
    return True


def find_spikes(
    history: list[int], threshold: float = SPIKE_THRESHOLD
) -> list[dict[str, float]]:
    """Шаги, где курс резко скакнул: индекс в истории и изменение в процентах."""
    spikes: list[dict[str, float]] = []
    for index in range(1, len(history)):
        prev = history[index - 1]
        if prev <= 0:
            continue
        change = (history[index] - prev) / prev
        if abs(change) >= threshold:
            spikes.append({"i": index, "change": round(change * 100, 1)})
    return spikes


def change_percent(history: list[int]) -> float:
    """Изменение за показанный отрезок истории, в процентах."""
    if len(history) < 2 or history[0] <= 0:
        return 0.0
    return (history[-1] - history[0]) / history[0] * 100.0
