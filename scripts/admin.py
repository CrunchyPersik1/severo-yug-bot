"""Админ-инструмент: раздачи и сбросы для всех игроков сразу.

Запускается локально, VPN не нужен — Supabase доступен напрямую.
Проще всего через admin.local.bat в корне проекта.

    admin.local.bat limits 2 2     выдать всем по 2 карты и по 2 спина на сегодня
    admin.local.bat limits         сбросить лимиты к обычным (1 и 1)
    admin.local.bat points 5000    накинуть всем 5000 очков
    admin.local.bat case 1         выдать всем по кейсу
    admin.local.bat card daniel 1  выдать всем по карте (очки тоже начислятся)
    admin.local.bat status         сводка по базе
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.cards import CARDS_BY_ID, card_rows, get_card  # noqa: E402
from app.db import Database  # noqa: E402
from app.gacha import day_key  # noqa: E402
from app.roulette import roulette_day_key  # noqa: E402

HELP = __doc__


async def act_limits(con, args: list[str]) -> str:
    drops = int(args[0]) if args else 1
    spins = int(args[1]) if len(args) > 1 else drops
    await con.execute(
        """
        update players
           set last_drop_day = $1, drop_uses = 0, drop_limit = $3,
               roulette_day = $2, roulette_uses = 0, roulette_limit = $4,
               updated_at = now()
        """,
        day_key(),
        roulette_day_key(),
        max(0, drops),
        max(0, spins),
    )
    total = await con.fetchval("select count(*) from players")
    return f"[ok] {total} игрокам выдано на сегодня: {drops} карт(ы) и {spins} спин(ов)"


async def act_points(con, args: list[str]) -> str:
    if not args:
        raise ValueError("укажи сколько очков: admin.local.bat points 5000")
    amount = int(args[0])
    await con.execute("update players set bonus_points = bonus_points + $1", amount)
    total = await con.fetchval("select count(*) from players")
    return f"[ok] {total} игрокам начислено по {amount} очков"


async def act_case(con, args: list[str]) -> str:
    count = int(args[0]) if args else 1
    if count < 1:
        raise ValueError("количество должно быть больше нуля")
    if count > 100:
        raise ValueError("больше 100 кейсов за раз — перебор")
    await con.execute(
        """
        insert into cases (user_id, source)
        select p.user_id, 'admin' from players p cross join generate_series(1, $1)
        """,
        count,
    )
    total = await con.fetchval("select count(*) from players")
    return f"[ok] {total} игрокам выдано по {count} кейс(ов)"


async def act_card(con, args: list[str]) -> str:
    if not args:
        raise ValueError("укажи карту: admin.local.bat card daniel 1")
    card_id = args[0].lstrip("#")
    if card_id not in CARDS_BY_ID:
        raise ValueError(f"карты {card_id} нет. Доступные: " + ", ".join(sorted(CARDS_BY_ID)))
    count = int(args[1]) if len(args) > 1 else 1
    if count < 1:
        raise ValueError("количество должно быть больше нуля")
    if count > 100:
        raise ValueError("больше 100 карт за раз — перебор")
    card = get_card(card_id)
    await con.execute(
        """
        insert into collection (user_id, card_id, count)
        select p.user_id, $1, $2 from players p
        on conflict (user_id, card_id) do update set count = collection.count + $2
        """,
        card_id,
        count,
    )
    await con.execute(
        "update players set bonus_points = bonus_points + $1", card.points * count
    )
    total = await con.fetchval("select count(*) from players")
    return (
        f"[ok] {total} игрокам выдано по {count} x {card.display_name} "
        f"и по {card.points * count} очков"
    )


async def act_status(con, args: list[str]) -> str:
    rows = await con.fetch(
        """
        select
            (select count(*) from players) as players,
            (select count(*) from collection) as kinds,
            (select coalesce(sum(count), 0) from collection) as cards,
            (select count(*) from inventory) as upgraded,
            (select count(*) from cases where opened = false and listed = false) as cases,
            (select count(*) from market where status = 'active') as lots,
            (select count(*) from players where drop_uses > 0) as used_drop,
            (select count(*) from players where roulette_uses > 0) as used_spin,
            (select count(*) from players where drop_limit > 1) as bonus
        """
    )
    r = rows[0]
    return "\n".join(
        [
            "Состояние базы",
            f"  игроков:            {r['players']}",
            f"  карт в коллекциях:  {r['cards']} ({r['kinds']} видов)",
            f"  улучшенных копий:   {r['upgraded']}",
            f"  закрытых кейсов:    {r['cases']}",
            f"  активных лотов:     {r['lots']}",
            f"  использовали /drop: {r['used_drop']}",
            f"  крутили рулетку:    {r['used_spin']}",
            f"  с бонусным лимитом: {r['bonus']}",
        ]
    )


COMMANDS = {
    "limits": act_limits,
    "points": act_points,
    "case": act_case,
    "card": act_card,
    "status": act_status,
}


async def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in {"help", "-h", "--help"}:
        print(HELP)
        return
    name, rest = args[0], args[1:]
    action = COMMANDS.get(name)
    if action is None:
        print("Неизвестная команда: " + name)
        print(HELP)
        sys.exit(1)

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("Не задан DATABASE_URL")

    db = Database(dsn)
    await db.connect()
    try:
        await db.init_schema()
        await db.upsert_cards(card_rows())
        async with db.pool.acquire() as con:
            print(await action(con, rest))
    except ValueError as error:
        sys.exit("Ошибка: " + str(error))
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
