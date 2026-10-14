"""Админ-действия: раздачи, изъятия и сводки.

Одна реализация на два входа: локальный CLI (scripts/admin.py) и команды
в боте (/admin ...). Логика работает на переданном соединении, поэтому
её можно звать откуда угодно.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from . import event
from .cards import CARDS_BY_ID, get_card
from .db import Database
from .gacha import day_key
from .items import BY_SLOT
from .market import sum_bonus
from .roulette import roulette_day_key

HELP = """Админ-команды:

status                     сводка по всей базе
soo текст                  разослать текст во все группы, где есть бот
event                      запустить/остановить ивент (при остановке — раздача)
minuta                     счастливая минута: шансы ×случайное на 60 секунд
kopilka                    включить/выключить кликер-копилку
player @ник                что у игрока: баланс, карты, копии, кейсы
limits 2 2                 выдать ВСЕМ по 2 карты и по 2 спина на сегодня
limits                     вернуть всем обычные лимиты (1 и 1)
limits @ник 2 2            выдать ЛИЧНО игроку 2 выдачи «Северо-Юг» и 2 спина
points 5000                накинуть ВСЕМ по 5000 очков
points @ник 5000           накинуть очков лично игроку (минус — списать)
case 1                     выдать ВСЕМ по кейсу
case @ник 5                выдать ОДНОМУ игроку 5 кейсов
card daniel 1              выдать ВСЕМ по карте
give @ник daniel 3         выдать ОДНОМУ игроку 3 карты
take @ник daniel 1         забрать у ОДНОГО игрока карту
stock                      показать курсы биржи
stock syug 1500            задать курс монеты (плавно доедет за пару шагов)
stock syug +10%            поднять (или -10% опустить) курс на процент
stock fix                  вылечить биржу, если курс замер

Игрока можно указывать как @username, так и числовым id.
give начисляет очки за карту, take списывает их же.
Биржа: монеты — syug, uchitel, misha, ludoman, kartofan."""


async def act_event(con: asyncpg.Connection, args: list[str]) -> str:
    """Включает ивент, а при выключении раздаёт всю копилку."""
    row = await con.fetchrow("select active from game_event where id = 1")
    active = bool(row["active"]) if row else False

    if not active:
        await con.execute(
            "update game_event set active = true, started_at = now() where id = 1"
        )
        await con.execute("delete from kopilka")
        return (
            "[ok] Ивент запущен!\n"
            "  · шансы «Северо-Юг» и рулетки подняты в 3 раза\n"
            "  · копилка обнулена и открыта\n"
            "  · кейсы и казино не тронуты\n"
            "Выключу ивент — раздам всё, что накликали."
        )

    async with con.transaction():
        result = await event.payout(con)
    return (
        "[ok] Ивент остановлен, копилка роздана.\n"
        f"  · игроков с наградой: {result['players']}\n"
        f"  · очков: {result['points']}\n"
        f"  · круток «Северо-Юг»: {result['drops']}\n"
        f"  · спинов рулетки: {result['spins']}\n"
        f"  · кейсов: {result['cases']}\n"
        f"  · карт: {result['cards']}\n"
        "Шансы вернулись к обычным."
    )


async def act_minuta(con: asyncpg.Connection, args: list[str]) -> str:
    """Счастливая минута: шансы ×N на 60 секунд."""
    boost = event.roll_happy_boost()
    await con.execute(
        "update game_event set happy_until = $1, happy_boost = $2, "
        "happy_chat = null, happy_announced = false where id = 1",
        event.happy_until(),
        boost,
    )
    return (
        f"[ok] 🍀 Счастливая минута!\n"
        f"  · шансы ×{boost} — {event.describe_boost(boost)}\n"
        f"  · действует {event.MINUTE_SECONDS} секунд"
    )


async def act_kopilka(con: asyncpg.Connection, args: list[str]) -> str:
    """Включает и выключает кликер-копилку."""
    row = await con.fetchrow("select clicker from game_event where id = 1")
    now_on = not bool(row["clicker"]) if row else True
    await con.execute("update game_event set clicker = $1 where id = 1", now_on)
    if now_on:
        return (
            "[ok] 🎮 Кликер включён.\n"
            "Игроки пишут «копилка» и кликают.\n"
            "Награды копятся и выдадутся, когда выключишь ивент."
        )
    return "[ok] Кликер выключен."


async def _resolve_player(con: asyncpg.Connection, target: str) -> dict[str, Any]:
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
            # Юзернейм есть не у всех, поэтому ищем ещё и по имени.
            rows = await con.fetch(
                "select user_id, first_name, username from players "
                "where lower(first_name) = lower($1) order by user_id",
                clean,
            )
            if len(rows) == 1:
                row = rows[0]
            elif len(rows) > 1:
                variants = ", ".join(
                    f"{r['first_name']} (id {r['user_id']})" for r in rows
                )
                raise ValueError(
                    f"под именем {clean} сразу несколько игроков: {variants}. "
                    "Уточни числовым id"
                )
    if row is None:
        raise ValueError(
            f"игрок {target} не найден. Пусть он хотя бы раз напишет боту — "
            "тогда я его узнаю"
        )
    return dict(row)


def _resolve_card(raw: str):
    card_id = (raw or "").lstrip("#").strip()
    if card_id not in CARDS_BY_ID:
        raise ValueError(
            "карты " + card_id + " нет. Доступные: " + ", ".join(sorted(CARDS_BY_ID))
        )
    return get_card(card_id)


def _item_of(slot: str, item_id: int | None):
    if item_id is None:
        return None
    return next((item for item in BY_SLOT[slot] if item.id == item_id), None)


def _copy_line(row) -> str:
    """Строка про улучшенную копию: название, предметы и итоговые проценты."""
    card = CARDS_BY_ID.get(row["card_id"])
    title = card.display_name if card else row["card_id"]
    names: list[str] = []
    bonus: dict[str, int] = {}
    for slot in ("aura", "background", "effect"):
        item = _item_of(slot, row[slot + "_id"])
        if item is not None:
            names.append(item.name)
            bonus = sum_bonus(bonus, item.bonus)
    totals = ", ".join(f"{stat} {value:+d}%" for stat, value in bonus.items())
    listed = " [на рынке]" if row["listed"] else ""
    return f"    #{row['id']} {title} — {totals}{listed}\n        {', '.join(names)}"


def _int_arg(args: list[str], index: int, default: int, name: str) -> int:
    if len(args) <= index:
        return default
    try:
        return int(args[index])
    except ValueError as error:
        raise ValueError(f"{name} должно быть числом, а не {args[index]}") from error


async def act_limits(con: asyncpg.Connection, args: list[str]) -> str:
    """limits 2 2 — всем, limits @ник 2 2 — лично.

    Числа — это выдачи «Северо-Юг» и спины рулетки. Всё, что не число,
    считается игроком, поэтому порядок аргументов не важен.
    """
    named = [arg for arg in args if not arg.lstrip("+-").isdigit()]
    numbers = [int(arg) for arg in args if arg.lstrip("+-").isdigit()]
    drops = numbers[0] if numbers else 1
    spins = numbers[1] if len(numbers) > 1 else drops
    if drops < 0 or spins < 0:
        raise ValueError("количество не может быть отрицательным")
    if drops > 100 or spins > 100:
        raise ValueError("больше 100 за раз — перебор")

    if named:
        player = await _resolve_player(con, named[0])
        await con.execute(
            """
            update players
               set last_drop_day = $2, drop_uses = 0, drop_limit = $3,
                   roulette_day = $4, roulette_uses = 0, roulette_limit = $5,
                   updated_at = now()
             where user_id = $1
            """,
            player["user_id"],
            day_key(),
            drops,
            roulette_day_key(),
            spins,
        )
        who = player["first_name"] or player["username"] or player["user_id"]
        return (
            f"[ok] {who}: {drops} выдач(и) «Северо-Юг» и {spins} спин(ов) рулетки "
            "на сегодня"
        )

    await con.execute(
        """
        update players
           set last_drop_day = $1, drop_uses = 0, drop_limit = $3,
               roulette_day = $2, roulette_uses = 0, roulette_limit = $4,
               updated_at = now()
        """,
        day_key(),
        roulette_day_key(),
        drops,
        spins,
    )
    total = await con.fetchval("select count(*) from players")
    return f"[ok] {total} игрокам выдано на сегодня: {drops} карт(ы) и {spins} спин(ов)"


async def act_points(con: asyncpg.Connection, args: list[str]) -> str:
    """points 5000 — всем, points @ник 5000 — лично. Минус списывает."""
    if not args:
        raise ValueError("формат: points 5000 (всем) или points @ник 5000 (одному)")

    if len(args) >= 2:
        # порядок не важен: points 5000 @ник и points @ник 5000 работают одинаково
        if args[0].lstrip("+-").isdigit():
            target, raw_amount = args[1], args[0]
        else:
            target, raw_amount = args[0], args[1]
        player = await _resolve_player(con, target)
        try:
            amount = int(raw_amount)
        except ValueError as error:
            raise ValueError(f"сумма должна быть числом, а не {raw_amount}") from error
        if not amount:
            raise ValueError("укажи сумму, отличную от нуля")
        balance = await con.fetchval(
            """
            update players set bonus_points = greatest(0, bonus_points + $2)
             where user_id = $1
            returning bonus_points
            """,
            player["user_id"],
            amount,
        )
        who = player["first_name"] or player["username"] or player["user_id"]
        return f"[ok] {who}: {amount:+d} очков, теперь {int(balance)}"

    amount = _int_arg(args, 0, 0, "количество очков")
    if not amount:
        raise ValueError("укажи сколько очков: points 5000")
    await con.execute(
        "update players set bonus_points = greatest(0, bonus_points + $1)", amount
    )
    total = await con.fetchval("select count(*) from players")
    if amount > 0:
        return f"[ok] {total} игрокам начислено по {amount} очков"
    return f"[ok] у {total} игроков списано по {abs(amount)} очков"


async def act_case(con: asyncpg.Connection, args: list[str]) -> str:
    """case 5 — всем, case @ник 5 — лично игроку. Порядок аргументов не важен."""
    if not args:
        raise ValueError("формат: case 5 (всем) или case @ник 5 (одному)")
    named = [arg for arg in args if not arg.lstrip("+-").isdigit()]
    numbers = [int(arg) for arg in args if arg.lstrip("+-").isdigit()]
    count = numbers[0] if numbers else 1
    if count < 1:
        raise ValueError("количество должно быть больше нуля")
    if count > 100:
        raise ValueError("больше 100 кейсов за раз — перебор")

    if named:
        player = await _resolve_player(con, named[0])
        await con.execute(
            """
            insert into cases (user_id, source)
            select $1, 'admin' from generate_series(1, $2)
            """,
            player["user_id"],
            count,
        )
        who = player["first_name"] or player["username"] or player["user_id"]
        return f"[ok] {who} получил {count} кейс(ов)"

    await con.execute(
        """
        insert into cases (user_id, source)
        select p.user_id, 'admin' from players p cross join generate_series(1, $1)
        """,
        count,
    )
    total = await con.fetchval("select count(*) from players")
    return f"[ok] {total} игрокам выдано по {count} кейс(ов)"


async def act_card(con: asyncpg.Connection, args: list[str]) -> str:
    if not args:
        raise ValueError("укажи карту: card daniel 1")
    card = _resolve_card(args[0])
    count = _int_arg(args, 1, 1, "количество карт")
    if count < 1:
        raise ValueError("количество должно быть больше нуля")
    if count > 100:
        raise ValueError("больше 100 карт за раз — перебор")
    await con.execute(
        """
        insert into collection (user_id, card_id, count)
        select p.user_id, $1, $2 from players p
        on conflict (user_id, card_id) do update set count = collection.count + $2
        """,
        card.card_id,
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


async def act_status(con: asyncpg.Connection, args: list[str]) -> str:
    row = await con.fetchrow(
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
    return "\n".join(
        [
            "Состояние базы",
            f"  игроков:            {row['players']}",
            f"  карт в коллекциях:  {row['cards']} ({row['kinds']} видов)",
            f"  улучшенных копий:   {row['upgraded']}",
            f"  закрытых кейсов:    {row['cases']}",
            f"  активных лотов:     {row['lots']}",
            f"  использовали /drop: {row['used_drop']}",
            f"  крутили рулетку:    {row['used_spin']}",
            f"  с бонусным лимитом: {row['bonus']}",
        ]
    )


async def act_player(con: asyncpg.Connection, args: list[str]) -> str:
    if not args:
        raise ValueError("укажи игрока: player @ник")
    player = await _resolve_player(con, args[0])
    uid = player["user_id"]
    row = await con.fetchrow(
        """
        select p.bonus_points, p.wins, p.losses, p.draws,
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
    copies = await con.fetch(
        """
        select i.id, i.card_id, i.listed,
               u.aura_id, u.background_id, u.effect_id
          from inventory i
          left join upgrades u on u.inventory_id = i.id
         where i.user_id = $1
         order by i.id
        """,
        uid,
    )
    name = player["first_name"] or player["username"] or "без имени"
    lines = [
        f"Игрок: {name} (@{player['username']}) id={uid}",
        f"  баланс:  {row['bonus_points']} очков",
        f"  бои:     {row['wins']} побед / {row['losses']} поражений / {row['draws']} ничьих",
        f"  карт:    {row['cards']} шт ({row['kinds']} видов), улучшенных копий: {row['upgraded']}",
        f"  кейсов:  {row['cases']}",
    ]
    if cards:
        lines.append("  стак (обычные копии):")
        for entry in cards:
            card = CARDS_BY_ID.get(entry["card_id"])
            title = card.display_name if card else entry["card_id"]
            lines.append(f"    #{entry['card_id']} {title} x{entry['count']}")
    if copies:
        lines.append("  улучшенные копии:")
        for row in copies:
            lines.append(_copy_line(row))
    return "\n".join(lines)


async def act_give(con: asyncpg.Connection, args: list[str]) -> str:
    if len(args) < 2:
        raise ValueError("формат: give @ник карта [количество]")
    player = await _resolve_player(con, args[0])
    card = _resolve_card(args[1])
    count = _int_arg(args, 2, 1, "количество карт")
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
    left = await con.fetchval(
        "select count from collection where user_id = $1 and card_id = $2",
        player["user_id"],
        card.card_id,
    )
    who = player["first_name"] or player["username"]
    return (
        f"[ok] {who} получил {count} x {card.display_name} и {card.points * count} очков "
        f"(теперь в стаке {left})"
    )


async def act_take(con: asyncpg.Connection, args: list[str]) -> str:
    if len(args) < 2:
        raise ValueError("формат: take @ник карта [количество]")
    player = await _resolve_player(con, args[0])
    card = _resolve_card(args[1])
    want = _int_arg(args, 2, 1, "количество карт")
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
    who = player["first_name"] or player["username"]
    return (
        f"[ok] у {who} забрано {taken} x {card.display_name} и {card.points * taken} очков "
        f"(осталось в стаке {int(have) - taken})"
    )


_STOCK_MIGRATIONS = (
    "alter table stocks add column if not exists pump_phase text",
    "alter table stocks add column if not exists pump_peak integer",
    "alter table stocks add column if not exists pump_home integer",
    "alter table stocks add column if not exists pump_at timestamptz",
    "create table if not exists stock_pumps ("
    "id integer primary key, next_at timestamptz not null default now())",
)


async def _stock_fix(con: asyncpg.Connection) -> str:
    """Лечит зависшую биржу: догоняет миграции и снимает залипшие пампы."""
    for statement in _STOCK_MIGRATIONS:
        await con.execute(statement)
    await con.execute(
        "update stocks set pump_phase = null, pump_peak = null, pump_home = null "
        "where pump_phase is not null"
    )
    await con.execute(
        "insert into stock_pumps (id, next_at) values (1, $1) "
        "on conflict (id) do update set next_at = excluded.next_at",
        datetime.now(timezone.utc) + timedelta(hours=1),
    )
    # Сдвигаем в прошлое: ближайший тик сразу двинет курс.
    await con.execute("update stocks set updated_at = now() - interval '20 seconds'")
    return (
        "✅ Биржа вылечена: миграции догнаны, залипшие пампы сняты, следующий "
        "памп — через час. Курс двинется на ближайшем тике (до 15 секунд)."
    )


async def act_stock(con: asyncpg.Connection, args: list[str]) -> str:
    """Курс биржи: показать, задать цель или вылечить зависшую биржу.

    stock                 — все монеты и когда был последний тик
    stock fix             — снять залипшие пампы и догнать миграции
    stock syug            — одна монета
    stock syug 1500       — цель 1500
    stock syug +10%       — цель = текущая × 1.1 (можно -10%)
    """
    if args and (args[0] or "").strip().lower() in ("fix", "фикс", "ремонт"):
        return await _stock_fix(con)

    if not args:
        rows = await con.fetch(
            "select slug, name, price, target_price, updated_at from stocks order by id"
        )
        if not rows:
            raise ValueError("Биржа ещё не создана — таблица stocks пуста.")
        now = datetime.now(timezone.utc)
        lines = ["Курсы биржи:"]
        for row in rows:
            target = (
                f"  → цель {int(row['target_price'])}" if row["target_price"] else ""
            )
            age = int((now - row["updated_at"]).total_seconds())
            lines.append(
                f"  {row['slug']:<9} {row['name']}: {int(row['price'])}{target}"
                f"  (тик {age} с назад)"
            )
        lines += [
            "",
            "Задать: stock <монета> <цена>  (или +10% / -10%)",
            "Если курс замер: stock fix",
        ]
        return "\n".join(lines)

    query = (args[0] or "").lstrip("#").strip().lower()
    row = await con.fetchrow("select * from stocks where slug = $1", query)
    if row is None:
        rows = await con.fetch(
            "select * from stocks where lower(name) = lower($1)", args[0].strip()
        )
        if len(rows) == 1:
            row = rows[0]
    if row is None:
        known = await con.fetch("select slug from stocks order by id")
        raise ValueError(
            "Нет такой монеты. Есть: " + ", ".join(str(r["slug"]) for r in known)
        )

    if len(args) < 2:
        target = (
            f", цель {int(row['target_price'])}" if row["target_price"] else ""
        )
        return (
            f"{row['name']} ({row['slug']}): сейчас {int(row['price'])}{target}. "
            f"Задать: stock {row['slug']} 1500"
        )

    raw = (args[1] or "").strip().replace(" ", "")
    if raw.endswith("%"):
        try:
            percent = float(raw[:-1]) / 100.0
        except ValueError as error:
            raise ValueError("Процент должен быть числом: +10% или -5%") from error
        target = max(1, round(int(row["price"]) * (1 + percent)))
    else:
        try:
            target = int(raw)
        except ValueError as error:
            raise ValueError("Цена должна быть числом, например: stock syug 1500") from error
        if target < 1:
            raise ValueError("Цена должна быть больше нуля")

    await con.execute(
        "update stocks set target_price = $2 where id = $1",
        int(row["id"]),
        int(target),
    )
    return (
        f"[ok] {row['name']}: {int(row['price'])} → {target}. "
        "Курс поедет к цели за пару шагов по 15 секунд."
    )


COMMANDS = {
    "event": act_event,
    "minuta": act_minuta,
    "kopilka": act_kopilka,
    "limits": act_limits,
    "points": act_points,
    "case": act_case,
    "card": act_card,
    "status": act_status,
    "player": act_player,
    "give": act_give,
    "take": act_take,
    "stock": act_stock,
    "курс": act_stock,
}


async def run(db: Database, name: str, args: list[str]) -> str:
    """Единая точка входа: CLI и бот зовут её одинаково."""
    action = COMMANDS.get(name)
    if action is None:
        raise ValueError("неизвестная команда: " + name + "\n\n" + HELP)
    async with db.pool.acquire() as con:
        return await action(con, args)
