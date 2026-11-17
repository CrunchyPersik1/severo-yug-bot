"""Промокоды: разовые подарки за код."""

from __future__ import annotations


from typing import Any

from .cards import get_card
from .db import Database
from .gacha import DROPS_PER_DAY, day_key


class PromoError(Exception):
    """Ошибку можно показать игроку."""


# Ключи уже в нормализованном виде (без пробелов, дефисов и регистра):
# их сравнивают с normalize(ввод игрока).
PROMOS: dict[str, dict[str, Any]] = {
    # сезонный код: даёт секретную учительницу
    "ocehb": {"kind": "card", "card": "elmira_secret", "note": "секретная учительница"},
    # 5 дополнительных попыток «Северо-Юг» на сегодня
    "североюн": {"kind": "drops", "amount": 5, "note": "5 круток «Северо-Юг»"},
    # бесплатный Миша
    "mishainpotato": {"kind": "card", "card": "misha", "note": "бесплатный Миша"},
    # 15 000 очков на баланс
    "mishakotletka": {"kind": "points", "amount": 15_000, "note": "15 000 очков"},
}


def normalize(code: str) -> str:
    return (code or "").strip().lower().replace(" ", "").replace("-", "")


async def redeem(db: Database, user_id: int, raw_code: str) -> str:
    """Гасит промокод и выдаёт награду. Возвращает текст для игрока."""
    code = normalize(raw_code)
    if not code:
        raise PromoError("Напиши код: <code>/promo OCEHb</code>")
    # Сначала база: коды из /admin promo. Старый словарь — на случай,
    # если базу ещё не наполняли.
    from .promo_db import PromoCodeError, PromoRepo

    try:
        from_db = await PromoRepo(db).redeem(user_id, code)
    except PromoCodeError as error:
        raise PromoError(str(error)) from error
    except Exception:  # noqa: BLE001 - база недоступна: работаем по словарю
        from_db = None
    if from_db is not None:
        granted = from_db["granted"]
        lines = "\n".join("· " + item for item in granted) if granted else "· награда выдана"
        note = f"\n\n<i>{from_db['note']}</i>" if from_db.get("note") else ""
        return "🎁 <b>Промокод принят!</b>\n\n" + lines + note

    entry = PROMOS.get(code)
    if entry is None:
        raise PromoError("🤷 Такого промокода нет.")
    if not await db.redeem_promo(user_id, code):
        raise PromoError("Этот промокод ты уже использовал.")

    kind = str(entry.get("kind", "card"))

    if kind == "points":
        amount = int(entry["amount"])
        balance = await db.add_points(user_id, amount)
        return (
            "🎁 <b>Промокод принят!</b>\n\n"
            f"💰 <b>+{amount}</b> очков на баланс.\n"
            f"💳 Теперь у тебя: <b>{balance}</b>"
        )

    if kind == "drops":
        amount = int(entry["amount"])
        left = await db.grant_drop_limit(user_id, day_key(), amount, DROPS_PER_DAY)
        return (
            "🎁 <b>Промокод принят!</b>\n\n"
            f"🎴 <b>+{amount}</b> попыток «Северо-Юг» на сегодня.\n"
            f"🎟 Осталось попыток: <b>{left}</b>"
        )

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
