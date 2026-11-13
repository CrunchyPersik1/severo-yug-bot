"""Набор наград: акции, топ-паки, ежедневка и мегаквест выдают одно и то же.

Один словарь на всё — `{"points": 0, "gems": 0, "cards": [], ...}`. Так цена,
описание и выдача не расходятся: магазин показывает ровно то, что запишет
`grant`, а оценка в очках считается из того же словаря.
"""

from __future__ import annotations

import json
from typing import Any

from .cards import get_card
from .cases import CASE_D_PRICE, CASE_PRICE, ULTRA_CASE_PRICE
from .market import market_price

# Сколько очков стоит один кристалл. По этому курсу считается «выгода»,
# и по нему же кристаллы продаются за очки.
GEM_RATE = 55_555

# Оценка того, что нельзя посчитать через карту.
SHARE_VALUE = 2_000      # одна акция биржи
WEAPON_VALUE = 45_000    # ствол из подземелья
SPIN_VALUE = 25_000      # платный спин кристальной рулетки

NUM_KEYS: tuple[str, ...] = (
    "points",
    "gems",
    "yugi",
    "cases_g",
    "cases_d",
    "cases_ultra",
    "spins",
    "shares",
    "vip_days",
)


def make(**kwargs: Any) -> dict[str, Any]:
    """Собирает набор: числа по умолчанию нули, карты и оружие — пусто."""
    bundle: dict[str, Any] = {key: 0 for key in NUM_KEYS}
    bundle["cards"] = []
    bundle["weapon"] = None
    for key, value in kwargs.items():
        if key in bundle:
            bundle[key] = value
        else:
            raise ValueError(f"Неизвестная награда: {key}")
    bundle["cards"] = [str(card) for card in bundle["cards"]]
    return bundle


def merge(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """Складывает два набора."""
    out = make()
    for key in NUM_KEYS:
        out[key] = int(first.get(key) or 0) + int(second.get(key) or 0)
    out["cards"] = list(first.get("cards") or []) + list(second.get("cards") or [])
    out["weapon"] = second.get("weapon") or first.get("weapon")
    return out


def value(bundle: dict[str, Any]) -> int:
    """Сколько это стоит в очках — для цены и для «выгоды» на витрине."""
    total = 0
    total += int(bundle.get("points") or 0)
    total += int(bundle.get("gems") or 0) * GEM_RATE
    total += int(bundle.get("yugi") or 0) // 10          # Юги дешевле очков
    total += int(bundle.get("cases_g") or 0) * CASE_PRICE
    total += int(bundle.get("cases_d") or 0) * CASE_D_PRICE
    total += int(bundle.get("cases_ultra") or 0) * ULTRA_CASE_PRICE
    total += int(bundle.get("spins") or 0) * SPIN_VALUE
    total += int(bundle.get("shares") or 0) * SHARE_VALUE
    total += int(bundle.get("vip_days") or 0) * 30_000
    if bundle.get("weapon"):
        total += WEAPON_VALUE
    for card_id in bundle.get("cards") or []:
        try:
            total += market_price(get_card(str(card_id)))
        except KeyError:
            continue
    return int(total)


def _plural(number: int, one: str, few: str, many: str) -> str:
    if number % 10 == 1 and number % 100 != 11:
        return one
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return few
    return many


plural = _plural


def _group(number: int) -> str:
    return f"{int(number):,}".replace(",", " ")


def labels(bundle: dict[str, Any]) -> list[str]:
    """Человеческое описание содержимого — для витрины и для тоста."""
    out: list[str] = []
    if bundle.get("points"):
        out.append(f"{_group(int(bundle['points']))} очков")
    if bundle.get("gems"):
        count = int(bundle["gems"])
        out.append(f"{count} {_plural(count, 'кристалл', 'кристалла', 'кристаллов')}")
    if bundle.get("yugi"):
        out.append(f"{_group(int(bundle['yugi']))} Югов")
    if bundle.get("cases_g"):
        count = int(bundle["cases_g"])
        out.append(f"{count} {_plural(count, 'кейс', 'кейса', 'кейсов')} 7Г")
    if bundle.get("cases_d"):
        count = int(bundle["cases_d"])
        out.append(f"{count} {_plural(count, 'кейс', 'кейса', 'кейсов')} 7Д")
    if bundle.get("cases_ultra"):
        count = int(bundle["cases_ultra"])
        out.append(f"{count} {_plural(count, 'кейс', 'кейса', 'кейсов')} «Ультра»")
    if bundle.get("spins"):
        count = int(bundle["spins"])
        out.append(f"{count} {_plural(count, 'крутка', 'крутки', 'круток')} рулетки")
    if bundle.get("shares"):
        count = int(bundle["shares"])
        out.append(f"{count} {_plural(count, 'акция', 'акции', 'акций')} биржи")
    for card_id in bundle.get("cards") or []:
        try:
            out.append(get_card(str(card_id)).display_name)
        except KeyError:
            continue
    if bundle.get("weapon"):
        out.append("оружие для подземелья")
    if bundle.get("vip_days"):
        out.append(f"VIP на {int(bundle['vip_days'])} дней")
    return out


def text(bundle: dict[str, Any]) -> str:
    return " + ".join(labels(bundle)) or "пусто"


async def grant(
    db: Any, con: Any, user_id: int, bundle: dict[str, Any]
) -> list[str]:
    """Выдаёт всё содержимое набора в одной транзакции вызывающего."""
    user_id = int(user_id)
    if bundle.get("points"):
        await con.execute(
            "update players set bonus_points = bonus_points + $2, "
            "updated_at = now() where user_id = $1",
            user_id,
            int(bundle["points"]),
        )
    if bundle.get("gems"):
        await con.execute(
            "update players set crystals = crystals + $2, updated_at = now() "
            "where user_id = $1",
            user_id,
            int(bundle["gems"]),
        )
    if bundle.get("yugi"):
        amount = int(bundle["yugi"])
        await con.execute(
            """
            insert into yugi (user_id, balance, total) values ($1, $2, $2)
            on conflict (user_id) do update
               set balance = yugi.balance + $2,
                   total = yugi.total + $2,
                   updated_at = now()
            """,
            user_id,
            amount,
        )
    for key, source in (
        ("cases_g", "shop"),
        ("cases_d", "case_d"),
        ("cases_ultra", "ultra"),
    ):
        count = int(bundle.get(key) or 0)
        if count > 0:
            await con.execute(
                "insert into cases (user_id, source) "
                "select $1, $2 from generate_series(1, $3::integer)",
                user_id,
                source,
                count,
            )
    if bundle.get("spins"):
        from .roulette import SPINS_PER_DAY

        await con.execute(
            """
            update players set
                roulette_uses = case when roulette_day = current_date then roulette_uses else 0 end,
                roulette_limit = case when roulette_day = current_date then roulette_limit else $3 end + $2,
                roulette_day = current_date,
                updated_at = now()
             where user_id = $1
            """,
            user_id,
            int(bundle["spins"]),
            SPINS_PER_DAY,
        )
    if bundle.get("shares"):
        await _grant_shares(con, user_id, int(bundle["shares"]))
    if bundle.get("vip_days"):
        await con.execute(
            "update players set vip_until = greatest(coalesce(vip_until, now()), now()) "
            "+ make_interval(days => $2::integer), updated_at = now() where user_id = $1",
            user_id,
            int(bundle["vip_days"]),
        )
    cards = [str(card) for card in (bundle.get("cards") or [])]
    for card_id in cards:
        await con.execute(
            """
            insert into collection (user_id, card_id, count) values ($1, $2, 1)
            on conflict (user_id, card_id) do update set count = collection.count + 1
            """,
            user_id,
            card_id,
        )
    weapon = bundle.get("weapon")
    if weapon:
        await con.execute(
            """
            insert into dungeon_hero (user_id, bag, weapon) values ($1, $2::jsonb, $3)
            on conflict (user_id) do update
               set bag = coalesce(dungeon_hero.bag, '[]'::jsonb) || $2::jsonb,
                   weapon = coalesce(dungeon_hero.weapon, $3),
                   updated_at = now()
            """,
            user_id,
            json.dumps([str(weapon)]),
            str(weapon),
        )
    return labels(bundle)


async def _grant_shares(con: Any, user_id: int, amount: int) -> None:
    """Акции биржи: одна случайная компания, с учётом лимита на монету."""
    from . import stocks as stocks_mod

    row = await con.fetchrow(
        "select id, price from stocks order by random() limit 1"
    )
    if row is None:
        return
    have = await con.fetchval(
        "select coalesce(shares, 0) from stock_holdings "
        "where user_id = $1 and stock_id = $2",
        user_id,
        int(row["id"]),
    )
    give = max(0, min(int(amount), stocks_mod.MAX_PER_STOCK - int(have or 0)))
    if give <= 0:
        return
    await con.execute(
        """
        insert into stock_holdings (user_id, stock_id, shares, spent)
        values ($1, $2, $3, 0)
        on conflict (user_id, stock_id) do update
           set shares = stock_holdings.shares + $3
        """,
        user_id,
        int(row["id"]),
        give,
    )
