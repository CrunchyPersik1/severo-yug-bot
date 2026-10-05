"""Локальная админка: раздачи, изъятия и сводки из cmd.

Та же логика, что и у команды /admin в боте — общий модуль app/admin_actions.py.

    admin.local.bat limits 2 2
    admin.local.bat give @ник daniel 3
    admin.local.bat help
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import admin_actions  # noqa: E402
from app.cards import card_rows  # noqa: E402
from app.db import Database  # noqa: E402


async def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in {"help", "-h", "--help"}:
        print(admin_actions.HELP)
        return

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("Не задан DATABASE_URL")

    db = Database(dsn)
    await db.connect()
    try:
        await db.init_schema()
        await db.upsert_cards(card_rows())
        print(await admin_actions.run(db, args[0], args[1:]))
    except ValueError as error:
        sys.exit("Ошибка: " + str(error))
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
