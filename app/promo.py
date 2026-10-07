"""Промокоды: разовые подарки за код."""

from __future__ import annotations

from typing import Any

from .cards import get_card
from .db import Database


class PromoError(Exception):
    """Ошибку можно показать игроку."""


PROMOS: dict[str, dict[str, Any]] = {
    # сезонный код: даёт секретную учительницу
    "ocehb": {"card": "elmira_secret", "note": "секретная учительница"},
}


def normalize(code: str) -> str:
    return (code or "").strip().lower().replace(" ", "").replace("-", "")


async def redeem(db: Database, user_id: int, raw_code: str) -> str:
    """Гасит промокод и выдаёт награду. Возвращает текст для игрока."""
    code = normalize(raw_code)
    if not code:
        raise PromoError("Напиши код: <code>/promo OCEHb</code>")
    entry = PROMOS.get(code)
    if entry is None:
        raise PromoError("🤷 Такого промокода нет.")
    if not await db.redeem_promo(user_id, code):
        raise PromoError("Этот промокод ты уже использовал.")

    card_id = str(entry["card"])
    card = get_card(card_id)
    await db.add_card(user_id, card_id)
    # Карта, как и при выпадении, сразу начисляет свои очки на баланс.
    await db.add_points(user_id, card.points)
    return (
        "🎁 <b>Промокод принят!</b>\n\n"
        f"{card.rarity_emoji} <b>{card.display_name}</b> ({card.rarity_title})\n"
        f"⚔️ {card.atk} · ❤️ {card.hp} · ✨ {card.ability.name}"
    )
