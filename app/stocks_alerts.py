"""Оповещения о росте курса: лс всем игрокам + общий чат групп.

Срабатывает, когда монета поднимается на 10% от прошлой отметки (и не чаще
раза в 15 минут на монету), поэтому спама почти нет, но на пампе монета
может «выстрелить» пару раз.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from aiogram import Bot

from .db import Database

log = logging.getLogger(__name__)


def _money(value: Any) -> str:
    return f"{int(value):,}".replace(",", " ")


def render_alerts(alerts: list[dict[str, Any]]) -> str:
    lines = ["📈 <b>Биржа на хайпе!</b>", ""]
    for alert in alerts:
        lines.append(
            f"{alert['emoji']} <b>{alert['name']}</b> "
            f"+{float(alert['change']):.1f}% → <b>{_money(alert['price'])}</b> очк."
        )
    lines += ["", "Залетай, пока растёт: /stocks"]
    return "\n".join(lines)


async def broadcast(bot: Bot, db: Database, alerts: list[dict[str, Any]]) -> None:
    if not alerts:
        return
    text = render_alerts(alerts)
    # Кто выключил уведомления у себя — тот их не получит. Остальные как жили:
    # отключение в одной группе не трогает ни другие группы, ни лички.
    off = await db.chats_alerts_off("alerts_stocks")

    # Личка всем игрокам (chat_id лички = id игрока).
    for user_id in await db.all_player_ids():
        if int(user_id) in off:
            continue
        with contextlib.suppress(Exception):
            await bot.send_message(user_id, text)
        await asyncio.sleep(0.05)

    # Группы — только в общий чат: без message_thread_id, иначе улетит в топики.
    for chat_id in await db.broadcast_targets():
        if int(chat_id) in off:
            continue
        try:
            await bot.send_message(chat_id, text)
        except Exception:  # noqa: BLE001
            with contextlib.suppress(Exception):
                await db.mark_chat_left(chat_id)
        await asyncio.sleep(0.05)
