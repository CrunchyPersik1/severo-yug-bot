"""Реферальные ссылки: игрок приводит друзей и получает попытки «Северо-Юг».

Ссылка — обычный Telegram deep-link вида
    https://t.me/<бот>?start=ref_<код>
Друг открывает его, бот получает /start ref_<код>, и пригласивший получает
+1 попытку «Северо-Юг» на сегодня.

Правила: один человек может быть приглашён только один раз; ссылка живёт, пока
не наберёт 25 человек; новую ссылку можно создать не раньше чем через 7 дней.
"""

from __future__ import annotations

import contextlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from aiogram import Bot

from .db import Database
from .gacha import DROPS_PER_DAY, day_key

log = logging.getLogger(__name__)

REF_PREFIX = "ref_"
LINK_LIMIT = 25
LINK_COOLDOWN = timedelta(days=7)

# Telegram разрешает в start-параметре только [A-Za-z0-9_-].
_CODE_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"


class ReferralError(Exception):
    """Ошибку можно показать игроку."""


def make_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))


def link_url(bot_username: str, code: str) -> str:
    return f"https://t.me/{bot_username}?start={REF_PREFIX}{code}"


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _humanize(delta: timedelta) -> str:
    total = max(0, int(delta.total_seconds()))
    days, remainder = divmod(total, 86400)
    hours = remainder // 3600
    if days:
        return f"{days} д {hours} ч"
    minutes = (remainder % 3600) // 60
    return f"{hours} ч {minutes} мин"


async def status(db: Database, user_id: int, bot_username: str) -> str:
    """Показывает действующую ссылку или создаёт новую, если неделя прошла."""
    last = await db.latest_ref_link(user_id)
    now = datetime.now(timezone.utc)
    if last is not None:
        age = now - _as_utc(last["created_at"])
        if age < LINK_COOLDOWN:
            uses = int(last["uses"])
            cap = int(last["max_uses"])
            left = max(0, cap - uses)
            lines = [
                "🔗 <b>Твоя реферальная ссылка</b>",
                "",
                link_url(bot_username, str(last["code"])),
                "",
                f"👥 Приглашено: <b>{uses}</b>/{cap} · осталось мест: <b>{left}</b>",
            ]
            if left <= 0 or not last["active"]:
                lines.append("Ссылка уже набрала лимит.")
            else:
                lines.append(
                    f"Новую можно будет создать через {_humanize(LINK_COOLDOWN - age)}."
                )
            return "\n".join(lines)

    code = ""
    for _ in range(8):
        code = make_code()
        try:
            await db.insert_ref_link(user_id, code, LINK_LIMIT)
        except ValueError:
            continue
        break
    else:
        raise ReferralError("Не получилось создать ссылку, попробуй ещё раз.")

    return "\n".join(
        [
            "🔗 <b>Реферальная ссылка создана</b>",
            "",
            link_url(bot_username, code),
            "",
            "За каждого друга, который зайдёт по ней, ты получаешь "
            "<b>+1 попытку «Северо-Юг»</b> на сегодня.",
            f"Лимит ссылки — <b>{LINK_LIMIT}</b> человек, новую можно создать "
            "не раньше чем через <b>7 дней</b>.",
            "Срабатывает один раз на человека.",
        ]
    )


async def redeem(
    db: Database, bot: Bot, referred_id: int, payload: str
) -> str | None:
    """Обрабатывает /start ref_<код>. None — это не реферальный переход."""
    if not payload.startswith(REF_PREFIX):
        return None
    code = payload[len(REF_PREFIX):].strip()
    if not code:
        return None

    claimed = await db.claim_referral(referred_id, code)
    if claimed is None:
        return None

    owner_id = int(claimed["owner_id"])
    left = await db.grant_drop_limit(owner_id, day_key(), 1, DROPS_PER_DAY)

    text = (
        "🎉 По твоей ссылке пришёл друг!\n"
        f"🎴 <b>+1</b> попытка «Северо-Юг» на сегодня. Осталось: <b>{left}</b>\n"
        f"👥 Приглашено: <b>{claimed['uses']}</b>/{claimed['max_uses']}"
    )
    if claimed["exhausted"]:
        text += " · ссылка набрала лимит"
    with contextlib.suppress(Exception):
        await bot.send_message(owner_id, text)

    return "🎉 Ты пришёл по приглашению друга! Меню — ниже."
