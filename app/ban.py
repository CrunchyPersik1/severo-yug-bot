"""Бан: забаненный игрок молча отсекается на входе.

Проверка стоит в middleware, поэтому не важно, какую команду он жмёт —
до обработчика он не дойдёт. Админ при этом не блокируется никогда.
"""

from __future__ import annotations

import logging

from aiogram import BaseMiddleware

from .config import settings

log = logging.getLogger(__name__)


class BanMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        db = data.get("db")
        user = data.get("event_from_user")
        if db is None or user is None:
            return await handler(event, data)
        if user.id in settings.admin_ids:
            return await handler(event, data)
        try:
            if await db.is_banned(user.id):
                return None
        except Exception:  # noqa: BLE001
            log.exception("Не смог проверить бан")
        return await handler(event, data)
