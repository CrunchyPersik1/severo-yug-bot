"""Биржа: курс, покупка и продажа акций. Всё в транзакциях."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import asyncpg

from . import pumps, stocks
from .db import Database

log = logging.getLogger(__name__)

HISTORY_POINTS = 60   # сколько точек курса показываем на графике
HISTORY_KEEP = 400    # сколько храним в базе


class StocksError(Exception):
    """Ошибку можно показать игроку."""


class StocksRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    @property
    def pool(self) -> asyncpg.Pool:
        return self.db._p()

    # ------------------------------------------------------------------ #
    # Курс
    # ------------------------------------------------------------------ #

    async def seed(self) -> None:
        known = [str(stock["slug"]) for stock in stocks.STOCKS]
        async with self.pool.acquire() as con:
            async with con.transaction():
                for stock in stocks.STOCKS:
                    await con.execute(
                        """
                        insert into stocks
                            (slug, name, emoji, base_price, price, prev_price,
                             volatility, alert_price)
                        values ($1, $2, $3, $4, $4, $4, $5, $4)
                        on conflict (slug) do update set
                            name = excluded.name,
                            emoji = excluded.emoji,
                            base_price = excluded.base_price,
                            volatility = excluded.volatility
                        """,
                        stock["slug"],
                        stock["name"],
                        stock["emoji"],
                        int(stock["base"]),
                        float(stock["vol"]),
                    )
                # У старых записей отметки оповещения не было — ставим по базе.
                await con.execute(
                    "update stocks set alert_price = base_price where alert_price <= 0"
                )
                # Расписание внезапных пампов: строка одна, заводим при первом
                # запуске и дальше только двигаем время следующего.
                await con.execute(
                    "insert into stock_pumps (id, next_at) values (1, $1) "
                    "on conflict (id) do nothing",
                    datetime.now(timezone.utc) + pumps.next_delay(),
                )
                # Цена/история могли остаться от старой базы (переименования монет,
                # смена базовой цены) и вылезти за коридор. Тогда график и проценты
                # врут (вплоть до +1200% при стоящем курсе). Чистим: точки истории
                # вне коридора удаляем, а саму цену возвращаем к базе.
                dirty = await con.fetch(
                    """
                    select distinct h.stock_id as id
                      from stock_history h
                      join stocks s on s.id = h.stock_id
                     where h.price::numeric > s.base_price * $1
                        or h.price::numeric < s.base_price * $2
                    """,
                    float(stocks.CEIL_MULT),
                    float(stocks.FLOOR_MULT),
                )
                for row in dirty:
                    await con.execute(
                        "delete from stock_history where stock_id = $1",
                        int(row["id"]),
                    )
                broken = await con.fetch(
                    """
                    select id from stocks
                     where price::numeric > base_price * $1
                        or price::numeric < base_price * $2
                    """,
                    float(stocks.CEIL_MULT),
                    float(stocks.FLOOR_MULT),
                )
                for row in broken:
                    await con.execute(
                        """
                        update stocks
                           set price = base_price, prev_price = base_price,
                               alert_price = base_price, target_price = null,
                               pump_phase = null, pump_peak = null, pump_home = null,
                               updated_at = now()
                         where id = $1
                        """,
                        int(row["id"]),
                    )
                # Если кто-то успел набрать больше лимита — забираем излишек и
                # возвращаем потраченные на него очки.
                await self._enforce_cap(con, stocks.MAX_PER_STOCK)
                # Компании, которых больше нет в каталоге: закрываем и
                # возвращаем держателям очки по текущему курсу.
                retired = await con.fetch(
                    "select id, price from stocks where not (slug = any($1::text[]))",
                    known,
                )
                for row in retired:
                    await con.execute(
                        """
                        update players p
                           set bonus_points = bonus_points + h.shares * $2
                          from stock_holdings h
                         where h.stock_id = $1 and h.user_id = p.user_id
                        """,
                        int(row["id"]),
                        int(row["price"]),
                    )
                    await con.execute("delete from stocks where id = $1", int(row["id"]))

    async def _enforce_cap(
        self, con: asyncpg.Connection, cap: int
    ) -> None:
        """Срезает излишек сверх лимита и возвращает за него потраченные очки."""
        await con.execute(
            """
            with over as (
                select h.user_id,
                       (h.shares - $1) as excess,
                       h.shares,
                       h.spent
                  from stock_holdings h
                 where h.shares > $1
            ),
            refund as (
                select user_id,
                       coalesce(sum(round(spent::numeric * excess / shares)::bigint), 0)
                           as amount
                  from over
                 group by user_id
            )
            update players p
               set bonus_points = bonus_points + r.amount
              from refund r
             where p.user_id = r.user_id and r.amount > 0
            """,
            int(cap),
        )
        await con.execute(
            """
            update stock_holdings
               set shares = $1,
                   spent = greatest(0, round(spent::numeric * $1 / shares)::bigint)
             where shares > $1
            """,
            int(cap),
        )

    async def tick(self) -> list[dict[str, Any]]:
        """Двигает курсы и возвращает монеты, о росте которых стоит сообщить."""
        now = datetime.now(timezone.utc)
        alerts: list[dict[str, Any]] = []
        async with self.pool.acquire() as con:
            async with con.transaction():
                rows = await con.fetch("select * from stocks for update")
                await self._maybe_start_pump(con, rows, now)
                # Перечитываем: могли только что поставить памп.
                rows = await con.fetch("select * from stocks for update")
                for row in rows:
                    await self._advance(con, row, now, alerts)
        return alerts

    async def _maybe_start_pump(
        self, con: asyncpg.Connection, rows: list, now: datetime
    ) -> None:
        """Раз в час запускает памп случайной монеты, если сейчас ничего не летит."""
        if any(row["pump_phase"] for row in rows):
            return
        schedule = await con.fetchrow(
            "select next_at from stock_pumps where id = 1 for update"
        )
        if schedule is None:
            await con.execute(
                "insert into stock_pumps (id, next_at) values (1, $1) "
                "on conflict (id) do nothing",
                now + pumps.next_delay(),
            )
            return
        if now < schedule["next_at"]:
            return
        candidates = [
            row
            for row in rows
            if pumps.has_room(
                int(row["price"]), int(row["base_price"]), stocks.CEIL_MULT
            )
        ] or list(rows)
        stock = pumps.pick(candidates)
        if stock is None:
            return
        price = int(stock["price"])
        ceiling = int(int(stock["base_price"]) * stocks.CEIL_MULT)
        await con.execute(
            """
            update stocks
               set pump_phase = 'up', pump_peak = $2, pump_home = $3,
                   pump_at = now(), target_price = null
             where id = $1
            """,
            int(stock["id"]),
            pumps.peak_price(price, ceiling),
            price,
        )
        await con.execute(
            "update stock_pumps set next_at = $1 where id = 1",
            now + pumps.next_delay(),
        )

    async def _advance(
        self, con: asyncpg.Connection, row, now: datetime, alerts: list[dict[str, Any]]
    ) -> None:
        volatility = float(row["volatility"])
        base = int(row["base_price"])
        elapsed = (now - row["updated_at"]).total_seconds()
        steps = int(elapsed // stocks.TICK_SECONDS)
        if steps <= 0:
            return
        steps = min(steps, stocks.MAX_CATCHUP_TICKS)
        price = int(row["price"])
        target = row["target_price"]
        target = int(target) if target is not None else None
        pump_phase = row["pump_phase"]
        pump_peak = int(row["pump_peak"]) if row["pump_peak"] is not None else 0
        pump_home = int(row["pump_home"]) if row["pump_home"] is not None else 0
        pump_done = False
        for _ in range(steps):
            if pump_phase == "up" and pump_peak:
                price = pumps.step_up(price, pump_peak)
                if price >= pump_peak:
                    pump_phase = "down"
            elif pump_phase == "down" and pump_home:
                price = pumps.step_down(price, pump_home)
                if price <= pump_home:
                    price = pump_home
                    pump_phase = None
                    pump_done = True
            else:
                price = stocks.next_price(price, base, volatility, target=target)
            await con.execute(
                "insert into stock_history (stock_id, price) values ($1, $2)",
                int(row["id"]),
                price,
            )
        reached = target is not None and price == target and pump_phase is None
        await con.execute(
            """
            update stocks
               set prev_price = price, price = $2, updated_at = now(),
                   target_price = case when $3 then null else target_price end,
                   pump_phase = $4,
                   pump_peak = case when $4 is null then null else pump_peak end,
                   pump_home = case when $4 is null then null else pump_home end,
                   alert_price = case when $5 then price else alert_price end,
                   alerted_at = case when $5 then now() else alerted_at end
             where id = $1
            """,
            int(row["id"]),
            price,
            reached,
            pump_phase,
            pump_done,
        )
        await con.execute(
            """
            delete from stock_history
             where stock_id = $1
               and id not in (
                   select id from stock_history
                    where stock_id = $1
                    order by id desc
                    limit $2
               )
            """,
            int(row["id"]),
            HISTORY_KEEP,
        )

        # Оповещение о росте: отметка поднимается вместе с курсом, поэтому за
        # один памп монета может «выстрелить» несколько раз, но не чаще
        # кулдауна — спама нет.
        alert_price = int(row["alert_price"] or 0)
        alerted_at = row["alerted_at"]
        since = (now - alerted_at).total_seconds() if alerted_at is not None else None
        if stocks.alert_due(price, alert_price, since):
            await con.execute(
                "update stocks set alert_price = $2, alerted_at = now() where id = $1",
                int(row["id"]),
                price,
            )
            alerts.append(
                {
                    "slug": row["slug"],
                    "name": row["name"],
                    "emoji": row["emoji"],
                    "price": price,
                    "from": alert_price,
                    "change": (
                        round((price - alert_price) / alert_price * 100, 1)
                        if alert_price
                        else 0.0
                    ),
                }
            )

    async def _history_rows(
        self, con: asyncpg.Connection, stock_id: int, limit: int = HISTORY_POINTS
    ) -> list[dict[str, Any]]:
        rows = await con.fetch(
            "select price, at from stock_history where stock_id = $1 "
            "order by id desc limit $2",
            int(stock_id),
            int(limit),
        )
        return [
            {"price": int(r["price"]), "at": r["at"]} for r in reversed(rows)
        ]

    # ------------------------------------------------------------------ #
    # Снимок для мини-аппки
    # ------------------------------------------------------------------ #

    async def overview(self, user_id: int) -> dict[str, Any]:
        async with self.pool.acquire() as con:
            rows = await con.fetch("select * from stocks order by id")
            holdings = await con.fetch(
                "select stock_id, shares, spent from stock_holdings where user_id = $1",
                user_id,
            )
            balance = await con.fetchval(
                "select coalesce(bonus_points, 0) from players where user_id = $1",
                user_id,
            )
            hold = {
                int(h["stock_id"]): (int(h["shares"]), int(h["spent"]))
                for h in holdings
            }
            items = []
            total_value = 0
            total_spent = 0
            now = datetime.now(timezone.utc)
            for row in rows:
                sid = int(row["id"])
                points = await self._history_rows(con, sid)
                hist = [point["price"] for point in points]
                spikes = stocks.find_spikes(hist)
                for spike in spikes:
                    at = points[int(spike["i"])]["at"]
                    spike["ago"] = max(0, int((now - at).total_seconds()))
                price = int(row["price"])
                shares, spent = hold.get(sid, (0, 0))
                value = stocks.sell_price(price) * shares
                total_value += value
                total_spent += spent
                items.append(
                    {
                        "slug": row["slug"],
                        "name": row["name"],
                        "emoji": row["emoji"],
                        "price": price,
                        "buy_price": stocks.buy_price(price),
                        "sell_price": stocks.sell_price(price),
                        "change": round(stocks.change_percent(hist), 2),
                        "history": hist,
                        "spikes": spikes,
                        "pump": bool(row["pump_phase"]),
                        "my_shares": shares,
                        "my_value": value,
                        "my_spent": spent,
                        "my_pnl": value - spent,
                        "room": max(0, stocks.MAX_PER_STOCK - shares),
                    }
                )
        return {
            "me": {"balance": int(balance or 0)},
            "stocks": items,
            "portfolio": {
                "value": total_value,
                "spent": total_spent,
                "pnl": total_value - total_spent,
            },
            "limits": {"max_per_stock": stocks.MAX_PER_STOCK},
        }

    # ------------------------------------------------------------------ #
    # Сделки
    # ------------------------------------------------------------------ #

    async def buy(self, user_id: int, slug: str, shares: int) -> dict[str, Any]:
        shares = int(shares)
        if shares < 1:
            raise StocksError("Сколько акций покупаем?")
        async with self.pool.acquire() as con:
            async with con.transaction():
                stock = await con.fetchrow(
                    "select * from stocks where slug = $1 for update", slug
                )
                if stock is None:
                    raise StocksError("Такой акции нет на бирже.")
                holding = await con.fetchrow(
                    "select shares from stock_holdings "
                    "where user_id = $1 and stock_id = $2",
                    user_id,
                    int(stock["id"]),
                )
                have = int(holding["shares"]) if holding else 0
                room = stocks.MAX_PER_STOCK - have
                if room <= 0:
                    raise StocksError(
                        f"На одну монету можно держать максимум "
                        f"{stocks.MAX_PER_STOCK}."
                    )
                if shares > room:
                    raise StocksError(
                        f"На одну монету максимум {stocks.MAX_PER_STOCK}. "
                        f"У тебя {have}, можно докупить ещё {room}."
                    )
                price = stocks.buy_price(int(stock["price"]))
                cost = price * shares
                row = await con.fetchrow(
                    """
                    update players set bonus_points = bonus_points - $2
                     where user_id = $1 and bonus_points >= $2
                    returning bonus_points
                    """,
                    user_id,
                    cost,
                )
                if row is None:
                    balance = await con.fetchval(
                        "select coalesce(bonus_points, 0) from players where user_id = $1",
                        user_id,
                    )
                    raise StocksError(
                        f"Не хватает очков: нужно {cost}, у тебя {int(balance or 0)}."
                    )
                await con.execute(
                    """
                    insert into stock_holdings (user_id, stock_id, shares, spent)
                    values ($1, $2, $3, $4)
                    on conflict (user_id, stock_id) do update set
                        shares = stock_holdings.shares + excluded.shares,
                        spent = stock_holdings.spent + excluded.spent
                    """,
                    user_id,
                    int(stock["id"]),
                    shares,
                    cost,
                )
        return {
            "slug": slug,
            "shares": shares,
            "price": price,
            "total": cost,
            "balance": int(row["bonus_points"]),
        }

    async def sell(self, user_id: int, slug: str, shares: int) -> dict[str, Any]:
        shares = int(shares)
        if shares < 1:
            raise StocksError("Сколько акций продаём?")
        async with self.pool.acquire() as con:
            async with con.transaction():
                stock = await con.fetchrow(
                    "select * from stocks where slug = $1 for update", slug
                )
                if stock is None:
                    raise StocksError("Такой акции нет на бирже.")
                holding = await con.fetchrow(
                    "select * from stock_holdings where user_id = $1 and stock_id = $2 "
                    "for update",
                    user_id,
                    int(stock["id"]),
                )
                have = int(holding["shares"]) if holding else 0
                if have < shares:
                    raise StocksError(f"У тебя только {have} акций этой компании.")
                price = stocks.sell_price(int(stock["price"]))
                proceeds = price * shares
                avg = int(holding["spent"]) / have
                spent_out = round(avg * shares)
                await con.execute(
                    "update stock_holdings set shares = shares - $3, "
                    "spent = greatest(0, spent - $4) "
                    "where user_id = $1 and stock_id = $2",
                    user_id,
                    int(stock["id"]),
                    shares,
                    spent_out,
                )
                await con.execute(
                    "delete from stock_holdings "
                    "where user_id = $1 and stock_id = $2 and shares <= 0",
                    user_id,
                    int(stock["id"]),
                )
                balance = await con.fetchval(
                    "update players set bonus_points = bonus_points + $2 "
                    "where user_id = $1 returning bonus_points",
                    user_id,
                    proceeds,
                )
        return {
            "slug": slug,
            "shares": shares,
            "price": price,
            "total": proceeds,
            "pnl": proceeds - spent_out,
            "balance": int(balance),
        }
