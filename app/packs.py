"""Топ-паки: только за кристаллы, смена вместе с акциями.

Цены фиксированные и намеренно «крупные»: кристалл — редкая валюта, а пак
должен читаться как покупка месяца, а не как ещё один кейс.
"""

from __future__ import annotations

import hashlib
import random
from typing import Any

from . import bundles

# Сколько паков максимум висит в витрине за период.
MAX_PER_PERIOD = 3

# Скидка «старой цены» — та же логика, что у акций: без неё не читается.
INFLATE = (1.5, 2.1)


def _pack(
    pack_id: str,
    title: str,
    subtitle: str,
    emoji: str,
    color: str,
    bundle: dict,
    price: int,
) -> dict[str, Any]:
    old_price = int(round(price * 1.75))
    return {
        "id": pack_id,
        "title": title,
        "subtitle": subtitle,
        "emoji": emoji,
        "color": color,
        "bundle": bundle,
        "contents": bundles.labels(bundle),
        "currency": "gems",
        "price": int(price),
        "old_price": old_price,
        "discount": max(5, int(round((1 - price / old_price) * 100))),
    }


# --------------------------------------------------------------------------- #
# Каталог паков. В период попадает от одного до MAX_PER_PERIOD штук.
# --------------------------------------------------------------------------- #

PACKS: tuple[dict[str, Any], ...] = (
    _pack(
        "mega",
        "МЕГА-НАБОР",
        "10 кейсов 7Г, ультралегендарка и VIP на 14 дней",
        "🎁",
        "#f59e0b",
        bundles.make(cases_g=10, cards=["valeriya"], vip_days=14),
        350,
    ),
    _pack(
        "triple",
        "ТРОЙНАЯ УЛЬТРА",
        "три ультралегендарные карты сразу",
        "🌈",
        "#22d3ee",
        bundles.make(cards=["valeriya", "daniyar_epic", "valeriya"]),
        150,
    ),
    _pack(
        "vault",
        "КРИСТАЛЬНЫЙ СУНДУК",
        "два кейса «7Д» и 100 000 очков",
        "🏫",
        "#7c3aed",
        bundles.make(cases_d=2, points=100_000),
        220,
    ),
    _pack(
        "arsenal",
        "АРСЕНАЛ",
        "топовый ствол, пять кейсов 7Г и десять круток",
        "⚔️",
        "#ef4444",
        bundles.make(weapon="sword_8_3", cases_g=5, spins=10),
        120,
    ),
    _pack(
        "investor",
        "ИНВЕСТОР",
        "200 акций биржи и 250 000 очков",
        "📈",
        "#0ea5e9",
        bundles.make(shares=200, points=250_000),
        140,
    ),
    _pack(
        "collector",
        "КОЛЛЕКЦИОНЕР",
        "по карте каждой высокой редкости: легендарная, секретная, ультимативная",
        "🃏",
        "#a855f7",
        bundles.make(cards=["daniel", "timur_secret", "valeriya"]),
        180,
    ),
)

PACK_BY_ID: dict[str, dict[str, Any]] = {pack["id"]: pack for pack in PACKS}


def roulette(period: int) -> list[dict[str, Any]]:
    """Какие паки выпали на этот период: от одного до трёх, без повторов."""
    seed = hashlib.sha256(f"packs|{period}".encode()).hexdigest()
    rng = random.Random(int(seed[:16], 16))
    count = rng.choices([1, 2, 3], weights=[35, 40, 25], k=1)[0]
    picks = rng.sample(list(PACKS), k=count)
    return picks


def ids_for(period: int) -> list[str]:
    return [pack["id"] for pack in roulette(period)]


def find(period: int, pack_id: str) -> dict[str, Any] | None:
    for pack in roulette(period):
        if pack["id"] == pack_id:
            return pack
    return None
