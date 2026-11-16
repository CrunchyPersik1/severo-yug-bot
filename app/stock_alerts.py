"""Уведомления о смене стока карт: личные и по согласию чата."""

from __future__ import annotations

import asyncio
from typing import Any

from aiogram import Bot

from . import card_stock

_last_window: int = 0


async def tick(bot: Bot, db: Any) -> None:
    """Раз в окно стока (5 минут) пишем тем, кто подписался на уведомления."""
    global _last_window
    window = card_stock.window_key()
    if _last_window == 0:
        _last_window = window
        return
    if window == _last_window:
        return
    _last_window = window
    items = card_stock.stock(window)

    subscribed: list[int] = []
    try:
        async with db.pool.acquire() as con:
            rows = await con.fetch(
                "select user_id from player_prefs where (prefs->>'stock_alerts')::boolean"
            )
        subscribed = [int(row["user_id"]) for row in rows]
    except Exception:  # noqa: BLE001
        return

    if not subscribed:
        return

    best = max(items, key=lambda item: item["price"]) if items else None
    hint = ""
    if best:
        hint = f"\nСамое дорогое в витрине: {best['price']} 💎"
    text = "🛒 Сток карт обновился — загляни в магазин." + hint
    for user_id in subscribed:
        try:
            await bot.send_message(user_id, text)
        except Exception:  # noqa: BLE001 - закрытый диалог не повод падать
            continue
        await asyncio.sleep(0.05)
