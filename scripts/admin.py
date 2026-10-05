"""Админ-инструмент: раздачи и сбросы для всех игроков сразу.

Запускается локально, VPN не нужен — Supabase доступен напрямую.
Проще всего через admin.local.bat в корне проекта.

    admin.local.bat limits 2 2              выдать всем по 2 карты и по 2 спина
    admin.local.bat limits                  сбросить лимиты к обычным (1 и 1)
    admin.local.bat points 5000             накинуть всем 5000 очков
    admin.local.bat case 1                  выдать всем по кейсу
    admin.local.bat card daniel 1           выдать всем по карте
    admin.local.bat status                  сводка по базе

    admin.local.bat player @ник             что у игрока: баланс, карты, копии
    admin.local.bat player 123456789        то же, но по числовому id

    admin.local.bat give @ник daniel 2      выдать игроку 2 карты (очки начислятся)
    admin.local.bat take @ник daniel 1      забрать карту обратно

Игрока можно указывать как @username, так и числовым id.
give и take работают с обычными копиями в стаке; улучшенные копии (inventory)
они не трогают.
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


async def _resolve_player(con, target: str) -> dict:
    """Находит игрока по @username или по числовому id."""
    clean = (target or "").lstrip("@").strip()
    if not clean:
        raise ValueError("укажи игрока: @username или числовой id")
    if clean.isdigit():
        row = await con.fetchrow(
            "select user_id, first_name, username from players where user_id = $1",
            int(clean),
        )
    else:
        row = await con.fetchrow(
            "select user_id, first_name, username from players "
            "where lower(username) = lower($1)",
            clean,
        )
    if row is None:
        raise ValueError(
            f"игрок {target} не найден. Посмотреть id можно в /market или через "
            "severo player, если он уже писал боту"
        )
    return dict(row)


def _resolve_card(raw: str):
    card_id = (raw or "").lstrip("#").strip()
    if card_id not in CARDS_BY_ID:
        raise ValueError(
            "карты " + card_id + " нет. Доступные: " + ", ".join(sorted(CARDS_BY_ID))
        )
    return get_card(card_id)


async def act_player(con, args: list[str]) -> str:
    if not args:
        raise ValueError("укажи игрока: severo player @ник")
    player = await _resolve_player(con, args[0])
    uid = player["user_id"]
    row = await con.fetchrow(
        """
        select p.bonus_points, p.wins, p.losses, p.draws, p.kills,
               (select count(*) from collection c where c.user_id = p.user_id) as kinds,
               (select coalesce(sum(count), 0) from collection c where c.user_id = p.user_id) as cards,
               (select count(*) from inventory i where i.user_id = p.user_id) as upgraded,
               (select count(*) from cases cs
                 where cs.user_id = p.user_id and cs.opened = false and cs.listed = false) as cases
          from players p where p.user_id = $1
        """,
        uid,
    )
    cards = await con.fetch(
        "select card_id, count from collection where user_id = $1 order by card_id", uid
    )
    name = player["first_name"] or player["username"] or "без имени"
    lines = [
        f"Игрок: {name} (@{player['username']}) id={uid}",
        f"  баланс:      {row['bonus_points']} очков",
        f"  бои:         {row['wins']} побед / {row['losses']} поражений / {row['draws']} ничьих",
        f"  карт:        {row['cards']} шт ({row['kinds']} видов), копий: {row['upgraded']}",
        f"  кейсов:      {row['cases']}",
    ]
    if cards:
        lines.append("  список:")
        for c in cards:
            card = CARDS_BY_ID.get(c["card_id"])
            title = card.display_name if card else c["card_id"]
            lines.append(f"    #{c['card_id']} {title} x{c['count']}")
    return "\n".join(lines)


async def act_give(con, args: list[str]) -> str:
    if len(args) < 2:
        raise ValueError("формат: severo give @ник карта [количество]")
    player = await _resolve_player(con, args[0])
    card = _resolve_card(args[1])
    count = int(args[2]) if len(args) > 2 else 1
    if count < 1:
        raise ValueError("количество должно быть больше нуля")
    if count > 100:
        raise ValueError("больше 100 карт за раз — перебор")
    await con.execute(
        """
        insert into collection (user_id, card_id, count) values ($1, $2, $3)
        on conflict (user_id, card_id) do update set count = collection.count + $3
        """,
        player["user_id"],
        card.card_id,
        count,
    )
    await con.execute(
        "update players set bonus_points = bonus_points + $1 where user_id = $2",
        card.points * count,
        player["user_id"],
    )
    total = await con.fetchval(
        "select count from collection where user_id = $1 and card_id = $2",
        player["user_id"],
        card.card_id,
    )
    return (
        f"[ok] {player['first_name'] or player['username']} получил "
        f"{count} x {card.display_name} и {card.points * count} очков "
        f"(теперь в стаке {total})"
    )


async def act_take(con, args: list[str]) -> str:
    if len(args) < 2:
        raise ValueError("формат: severo take @ник карта [количество]")
    player = await _resolve_player(con, args[0])
    card = _resolve_card(args[1])
    want = int(args[2]) if len(args) > 2 else 1
    if want < 1:
        raise ValueError("количество должно быть больше нуля")

    have = await con.fetchval(
        "select count from collection where user_id = $1 and card_id = $2",
        player["user_id"],
        card.card_id,
    )
    if not have:
        raise ValueError(
            f"у игрока нет карты {card.display_name} в стаке "
            "(улучшенные копии админка не трогает)"
        )
    taken = min(int(have), want)
    if taken >= int(have):
        await con.execute(
            "delete from collection where user_id = $1 and card_id = $2",
            player["user_id"],
            card.card_id,
        )
    else:
        await con.execute(
            "update collection set count = count - $3 where user_id = $1 and card_id = $2",
            player["user_id"],
            card.card_id,
            taken,
        )
    await con.execute(
        "update players set bonus_points = greatest(0, bonus_points - $1) where user_id = $2",
        card.points * taken,
        player["user_id"],
    )
    left = int(have) - taken
    return (
        f"[ok] у {player['first_name'] or player['username']} забрано "
        f"{taken} x {card.display_name} и {card.points * taken} очков "
        f"(осталось в стаке {left})"
    )


COMMANDS = {
    "limits": act_limits,
    "points": act_points,
    "case": act_case,
    "card": act_card,
    "status": act_status,
    "player": act_player,
    "give": act_give,
    "take": act_take,
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
