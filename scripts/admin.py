"""Локальная админка: раздачи, изъятия и сводки из cmd.

Та же логика, что и у команды /admin в боте — общий модуль app/admin_actions.py.

    admin.local.bat limits 2 2
    admin.local.bat give @ник daniel 3
    admin.local.bat log            лента за 30 минут
    admin.local.bat watch          живая лента, дописывается сама
    admin.local.bat help
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import admin_actions  # noqa: E402
from app import game_log  # noqa: E402
from app.cards import card_rows  # noqa: E402
from app.db import Database  # noqa: E402


def _live_args(args: list[str]) -> tuple[int, int, str | None]:
    """Разбирает аргументы режима watch: минуты, сколько показать сначала, игрок."""
    minutes, backlog, target = 30, 25, None
    for arg in args:
        if arg.startswith("@"):
            target = arg.lstrip("@")
        elif arg.isdigit():
            value = int(arg)
            if target is not None and backlog == 25:
                backlog = value
            elif minutes == 30:
                minutes = value
            else:
                backlog = value
    return minutes, backlog, target


async def watch(db: Database, args: list[str]) -> None:
    """Живая лента: печатает новое по мере появления.

    Опрашиваем базу раз в 2 секунды по id, а не по времени: id — bigserial,
    поэтому «что нового» определяется точно и без пропусков на границе окна.
    Ctrl+C — выход.
    """
    minutes, backlog, target = _live_args(args)

    print(game_log.frame("живой лог — Ctrl+C чтобы выйти"))
    async with db.pool.acquire() as con:
        rows = await game_log.recent(con, minutes=minutes, limit=backlog, username=target)
        for row in reversed(rows):
            print(game_log.line(row))
        last_id = max((int(row["id"]) for row in rows), default=0)
        if not rows:
            print("(пока тихо — жду действий)")

    empty_ticks = 0
    while True:
        await asyncio.sleep(2)
        try:
            async with db.pool.acquire() as con:
                rows = await con.fetch(
                    "select * from game_log where id > $1 order by id asc limit 200",
                    last_id,
                )
        except Exception as error:  # noqa: BLE001
            # Сеть до пулера иногда отваливается на пару секунд — не выходим.
            print(f"… связь с базой потеряна, пробую ещё: {error}")
            await asyncio.sleep(3)
            continue

        if not rows:
            empty_ticks += 1
            # Раз в минуту напоминаем, что всё ещё смотрим: иначе похоже,
            # что консоль зависла.
            if empty_ticks % 30 == 0:
                print("… тихо")
            continue

        empty_ticks = 0
        for row in rows:
            last_id = int(row["id"])
            if target:
                who = str(row["who"] or "").lower()
                if target.lower() not in who:
                    continue
            print(game_log.line(row))
        sys.stdout.flush()


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
        if args[0] in {"watch", "смотреть", "tail"}:
            try:
                await watch(db, args[1:])
            except KeyboardInterrupt:
                print("\nвыход")
            return
        await db.init_schema()
        await db.upsert_cards(card_rows())
        print(await admin_actions.run(db, args[0], args[1:]))
    except ValueError as error:
        sys.exit("Ошибка: " + str(error))
    finally:
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
