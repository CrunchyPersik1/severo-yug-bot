"""Акции магазина: 4 общих + 2 личных, смена раз в ЧЕТЫРЕ дня.

Акция — это пачка наград за одну цену в одной валюте. Генерация
детерминирована: у всех игроков одинаковые четыре общие акции, а личные
считаются от пары (игрок, период). Перезагрузка страницы ничего не меняет,
перезапуск сервиса тоже — акции живут в сиде, а не в базе. В базе только
то, что игрок купил.

Цена честная относительно содержимого (функция `bundles.value`), а вот
«старая цена» завышена намеренно: без неё скидка не читается.
"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from . import bundles
from .cards import CARDS_BY_RARITY
from .dungeon import WEAPON_KINDS

PERIOD_DAYS = 4
SHARED_SLOTS = 4
PERSONAL_SLOTS = 2
EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
RESET_HOUR_UTC = 15  # смена акций вместе с рулеткой, 20:00 по ЕКБ

# С этой суммы содержимое начинает продаваться за кристаллы.
GEMS_FROM_VALUE = 250_000

# Больше 30% не рисуем: такие скидки уже не читаются как честные.
MAX_DISCOUNT = 30

CURRENCY_POINTS = "points"
CURRENCY_GEMS = "gems"


def period_of(moment: datetime | None = None) -> int:
    """Номер четырёхдневки. Внутри периода акции не меняются."""
    moment = moment or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    shifted = moment.astimezone(timezone.utc) - timedelta(hours=RESET_HOUR_UTC)
    return int((shifted - EPOCH).total_seconds() // (86_400 * PERIOD_DAYS))


def period_end(moment: datetime | None = None) -> datetime:
    """Когда акции сменятся."""
    number = period_of(moment) + 1
    return EPOCH + timedelta(days=number * PERIOD_DAYS, hours=RESET_HOUR_UTC)


def period_text(moment: datetime | None = None) -> str:
    moment = moment or datetime.now(timezone.utc)
    seconds = (period_end(moment) - moment).total_seconds()
    days = int(max(0, seconds) // 86_400)
    hours = int(max(0, seconds) % 86_400 // 3600)
    if days:
        return f"Смена через {days} д {hours} ч"
    minutes = int(max(0, seconds) % 3600 // 60)
    return f"Смена через {hours} ч {minutes} мин"


def _rng(*parts: Any) -> random.Random:
    seed = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return random.Random(int(seed[:16], 16))


# --------------------------------------------------------------------------- #
# Шаблоны акций: каждый возвращает (bundle, title, subtitle, emoji, color)
# --------------------------------------------------------------------------- #


def _cards(rng: random.Random) -> tuple[dict, str, str, str, str]:
    rarity = rng.choices(
        ["epic", "mythic", "legendary", "secret", "ultimate"],
        weights=[38, 28, 18, 10, 6],
        k=1,
    )[0]
    pool = CARDS_BY_RARITY[rarity]
    count = rng.choices([1, 2, 3], weights=[55, 30, 15], k=1)[0]
    picks = rng.sample(pool, k=min(count, len(pool)))
    titles = {
        "epic": "Эпический",
        "mythic": "Мифический",
        "legendary": "Легендарный",
        "secret": "Секретный",
        "ultimate": "Ультимативный",
    }
    bundle = bundles.make(cards=[card.card_id for card in picks])
    names = ", ".join(card.display_name for card in picks[:2])
    word = bundles.plural(len(picks), "карта", "карты", "карт")
    return (
        bundle,
        f"Набор «{titles[rarity]}»",
        f"{len(picks)} {word}: {names}" + ("…" if len(picks) > 2 else ""),
        "🃏",
        "#a855f7",
    )


def _teacher(rng: random.Random) -> tuple[dict, str, str, str, str]:
    pool = CARDS_BY_RARITY["teacher"]
    card = rng.choice(pool)
    return (
        bundles.make(cards=[card.card_id]),
        "Учитель в коллекцию",
        card.display_name + " · " + str(card.ability.name),
        "🟤",
        "#a16207",
    )


def _cases_g(rng: random.Random) -> tuple[dict, str, str, str, str]:
    count = rng.randint(3, 10)
    word = bundles.plural(count, "кейс", "кейса", "кейсов")
    return (
        bundles.make(cases_g=count),
        f"{count} {word} 7Г",
        "внутри от эпической до ультралегендарной",
        "📦",
        "#15803d",
    )


def _case_d(rng: random.Random) -> tuple[dict, str, str, str, str]:
    count = rng.randint(1, 2)
    return (
        bundles.make(cases_d=count),
        f"Кейс «7Д класс»" + (" ×2" if count > 1 else ""),
        "27 карт второго класса",
        "🏫",
        "#7c3aed",
    )


def _case_ultra(rng: random.Random) -> tuple[dict, str, str, str, str]:
    count = rng.randint(1, 3)
    return (
        bundles.make(cases_ultra=count),
        "Кейс «Ультра»" + (f" ×{count}" if count > 1 else ""),
        "0.01% на Садыкова или Леру",
        "🎟",
        "#b45309",
    )


def _spins(rng: random.Random) -> tuple[dict, str, str, str, str]:
    count = rng.randint(2, 6)
    word = bundles.plural(count, "крутка", "крутки", "круток")
    return (
        bundles.make(spins=count),
        f"{count} {word} рулетки",
        "сверх дневного лимита",
        "🎡",
        "#dc2626",
    )


def _shares(rng: random.Random) -> tuple[dict, str, str, str, str]:
    count = rng.choice([20, 30, 50, 75, 100])
    word = bundles.plural(count, "акция", "акции", "акций")
    return (
        bundles.make(shares=count),
        f"Пакет акций · {count} {word}",
        "случайная компания с биржи",
        "📈",
        "#0ea5e9",
    )


def _yugi(rng: random.Random) -> tuple[dict, str, str, str, str]:
    amount = rng.choice([50_000, 100_000, 150_000, 250_000])
    return (
        bundles.make(yugi=amount),
        "Юги в кликер",
        "на постройки и древо",
        "🍪",
        "#f97316",
    )


def _gems(rng: random.Random) -> tuple[dict, str, str, str, str]:
    count = rng.choice([3, 5, 7, 10, 12])
    return (
        bundles.make(gems=count),
        f"{count} кристаллов",
        "валюта для топ-паков",
        "💎",
        "#22d3ee",
    )


def _weapon(rng: random.Random) -> tuple[dict, str, str, str, str]:
    rank = rng.randint(3, 8)
    variant = rng.randint(0, 4)
    kind = rng.choice(list(WEAPON_KINDS))
    weapon_id = f"{kind}_{rank}_{variant}"
    return (
        bundles.make(weapon=weapon_id),
        "Ствол для подземелья",
        f"ранг {rank + 1} · сразу в сумку",
        "⚔️",
        "#ef4444",
    )


# Мешка очков тут нет и не будет: продавать очки за очки — абсурд.
TEMPLATES: tuple = (
    (_cards, 30),
    (_teacher, 8),
    (_cases_g, 16),
    (_case_d, 6),
    (_case_ultra, 6),
    (_spins, 8),
    (_shares, 8),
    (_yugi, 6),
    (_gems, 6),
    (_weapon, 4),
)


def _build(period: int, slot: int, user_id: int | None) -> dict[str, Any]:
    """Одна акция. Одинаковая для всех при user_id=None."""
    rng = _rng("deal", period, slot, user_id or 0)
    functions = [item[0] for item in TEMPLATES]
    weights = [item[1] for item in TEMPLATES]
    builder = rng.choices(functions, weights=weights, k=1)[0]
    bundle, title, subtitle, emoji, color = builder(rng)
    real = bundles.value(bundle)

    # Валюта: кристаллы — только для дорогого и только если это не кристаллы.
    currency = CURRENCY_POINTS
    if real >= GEMS_FROM_VALUE and not bundle.get("gems") and rng.random() < 0.65:
        currency = CURRENCY_GEMS

    # Кристаллы — конвертируемая валюта: скидку на них почти не даём,
    # иначе получается арбитраж «купи акцию → продай кристаллы дороже».
    if bundle.get("gems"):
        currency = CURRENCY_POINTS
        # floor, а не round: цена никогда не должна перевалить за стоимость
        price = max(1000, int(real * rng.uniform(0.85, 1.0) / 1000.0) * 1000)
    elif currency == CURRENCY_GEMS:
        price = max(1, int(round(real / bundles.GEM_RATE * rng.uniform(0.55, 0.7))))
    else:
        price = max(1000, int(round(real * rng.uniform(0.5, 0.7) / 1000.0)) * 1000)

    # Скидка — не на всё и не больше 30%: большие числа не верят.
    discount = 0
    if rng.random() < 0.6:
        discount = int(round(rng.uniform(10, MAX_DISCOUNT)))
    if discount:
        raw = price / (1 - discount / 100.0)
        step = 1000 if currency == CURRENCY_POINTS else 1
        old_price = max(price + step, int(round(raw / step)) * step)
        discount = max(1, min(MAX_DISCOUNT, int(round((1 - price / old_price) * 100))))
    else:
        old_price = price
    return {
        "id": f"p{period}-{'u' if user_id else 's'}{slot}",
        "kind": builder.__name__.lstrip("_"),
        "title": title,
        "subtitle": subtitle,
        "emoji": emoji,
        "color": color,
        "bundle": bundle,
        "contents": bundles.labels(bundle),
        "currency": currency,
        "price": int(price),
        "old_price": int(old_price),
        "discount": discount,
        "personal": user_id is not None,
    }


def shared(period: int) -> list[dict[str, Any]]:
    """Четыре акции, одинаковые для всех игроков."""
    return [_build(period, slot, None) for slot in range(SHARED_SLOTS)]


def personal(period: int, user_id: int) -> list[dict[str, Any]]:
    """Две личные акции — считаются от пары (игрок, период)."""
    return [
        _build(period, SHARED_SLOTS + slot, int(user_id))
        for slot in range(PERSONAL_SLOTS)
    ]


def all_for(user_id: int, period: int) -> list[dict[str, Any]]:
    """Шесть плиток витрины: четыре общих, две личных."""
    return shared(period) + personal(period, user_id)


def find(user_id: int, period: int, deal_id: str) -> dict[str, Any] | None:
    for deal in all_for(user_id, period):
        if deal["id"] == deal_id:
            return deal
    return None
