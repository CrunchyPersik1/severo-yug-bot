
"""Хранилище Северо-Пасса: прогресс, квесты, покупки, награды.

Вся логика очков и уровней — в pass_config; здесь только база и выдача
наград через bundles.grant (та же транзакция, что и отметка о получении).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from . import bundles, pass_config, pass_quests, pass_rewards

SKIN_CARD = "valeriya_academy"


class PassError(Exception):
    """Ошибку можно показать игроку."""


class PassRepo:
    def __init__(self, db: Any) -> None:
        self.db = db

    @property
    def pool(self):
        return self.db._p()

    # ------------------------------------------------------------------ #
    # Прогресс
    # ------------------------------------------------------------------ #

    async def progress(self, user_id: int, season: str | None = None) -> dict[str, Any]:
        season = season or pass_config.season_key()
        async with self.pool.acquire() as con:
            row = await con.fetchrow(
                "select * from pass_progress where user_id = $1 and season = $2",
                int(user_id),
                season,
            )
            if row is None:
                await con.execute(
                    """
                    insert into pass_progress (user_id, season)
                    values ($1, $2) on conflict do nothing
                    """,
                    int(user_id),
                    season,
                )
                row = await con.fetchrow(
                    "select * from pass_progress where user_id = $1 and season = $2",
                    int(user_id),
                    season,
                )
        xp = int(row["xp"] or 0)
        level, into, need = pass_config.xp_into_level(xp)
        return {
            "season": season,
            "xp": xp,
            "level": level,
            "into": into,
            "need": need,
            "plus": bool(row["plus"]),
            "premium": bool(row["premium"]),
            "claimed_free": self._json(row["claimed_free"]),
            "claimed_plus": self._json(row["claimed_plus"]),
            "claimed_prem": self._json(row["claimed_prem"]),
            "bonus_claimed": int(row["bonus_claimed"] or 0),
            "bonus_picks": self._json(row["bonus_picks"]),
            "bonus_steps": pass_config.bonus_steps(xp),
        }

    @staticmethod
    def _json(value: Any) -> list:
        if isinstance(value, str):
            try:
                return json.loads(value or "[]")
            except ValueError:
                return []
        return list(value or [])

    async def add_xp(self, user_id: int, amount: int, source: str = "квест") -> int:
        """Начисляет очки пасса сезона. Возвращает новый XP."""
        if int(amount) <= 0:
            return 0
        season = pass_config.season_key()
        async with self.pool.acquire() as con:
            await con.execute(
                """
                insert into pass_progress (user_id, season, xp)
                values ($1, $2, $3)
                on conflict (user_id, season) do update
                   set xp = pass_progress.xp + $3,
                       updated_at = now()
                """,
                int(user_id),
                season,
                int(amount),
            )
            return int(
                await con.fetchval(
                    "select xp from pass_progress where user_id = $1 and season = $2",
                    int(user_id),
                    season,
                )
                or 0
            )

    # ------------------------------------------------------------------ #
    # Квесты дня
    # ------------------------------------------------------------------ #

    async def quests(self, user_id: int, day: date | None = None) -> list[dict[str, Any]]:
        """Квесты на день: создаются один раз, baseline снимается тогда же."""
        season = pass_config.season_key()
        day = day or datetime.now(pass_config.EKB).date()
        plan = pass_quests.daily(season, day)
        async with self.pool.acquire() as con:
            async with con.transaction():
                existing = await con.fetch(
                    "select * from pass_quests where user_id = $1 and season = $2 and day = $3",
                    int(user_id),
                    season,
                    day,
                )
                have = {int(row["slot"]) for row in existing}
                for quest in plan:
                    if int(quest["slot"]) in have:
                        continue
                    baseline = 0
                    try:
                        baseline = int(await con.fetchval(quest["sql"], int(user_id)) or 0)
                    except Exception:  # noqa: BLE001
                        baseline = 0
                    await con.execute(
                        """
                        insert into pass_quests
                            (user_id, season, day, slot, tier, quest_key, need,
                             baseline, xp, plus_only)
                        values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                        on conflict (user_id, season, day, slot) do nothing
                        """,
                        int(user_id),
                        season,
                        day,
                        int(quest["slot"]),
                        quest["tier"],
                        quest["key"],
                        int(quest["need"]),
                        baseline,
                        int(quest["xp"]),
                        bool(quest["plus"]),
                    )
                rows = await con.fetch(
                    "select * from pass_quests where user_id = $1 and season = $2 and day = $3 "
                    "order by slot",
                    int(user_id),
                    season,
                    day,
                )
        out: list[dict[str, Any]] = []
        for row in rows:
            plan_item = next(
                (item for item in plan if int(item["slot"]) == int(row["slot"])), None
            )
            sql = plan_item["sql"] if plan_item else None
            current = 0
            if sql:
                try:
                    async with self.pool.acquire() as con:
                        current = int(await con.fetchval(sql, int(user_id)) or 0)
                except Exception:  # noqa: BLE001
                    current = 0
            done = max(0, current - int(row["baseline"]))
            out.append(
                {
                    "slot": int(row["slot"]),
                    "tier": row["tier"],
                    "key": row["quest_key"],
                    "title": (plan_item or {}).get("title", row["quest_key"]),
                    "need": int(row["need"]),
                    "xp": int(row["xp"]),
                    "progress": min(done, int(row["need"])),
                    "claimed": bool(row["claimed"]),
                    "plus": bool(row["plus_only"]),
                    "ready": done >= int(row["need"]) and not bool(row["claimed"]),
                }
            )
        return out

    async def claim_quest(self, user_id: int, slot: int, has_plus: bool) -> dict[str, Any]:
        season = pass_config.season_key()
        day = datetime.now(pass_config.EKB).date()
        async with self.pool.acquire() as con:
            async with con.transaction():
                row = await con.fetchrow(
                    "select * from pass_quests where user_id = $1 and season = $2 "
                    "and day = $3 and slot = $4 for update",
                    int(user_id),
                    season,
                    day,
                    int(slot),
                )
                if row is None:
                    raise PassError("Такого квеста нет")
                if row["claimed"]:
                    raise PassError("Награда уже забрана")
                if row["plus_only"] and not has_plus:
                    raise PassError("Этот квест доступен только с Северо-Пасс+")
                await con.execute(
                    "update pass_quests set claimed = true, claimed_at = now() "
                    "where id = $1",
                    int(row["id"]),
                )
        xp = await self.add_xp(user_id, int(row["xp"]), "квест")
        return {"xp": xp, "amount": int(row["xp"])}

    # ------------------------------------------------------------------ #
    # Покупки
    # ------------------------------------------------------------------ #

    async def buy(self, user_id: int, kind: str) -> dict[str, Any]:
        """kind: plus | premium | upgrade. Гемы берём с игрока здесь же."""
        season = pass_config.season_key()
        state = await self.progress(user_id, season)
        if kind == "plus":
            if state["plus"]:
                raise PassError("Северо-Пасс+ уже куплен")
            price = pass_config.PRICE_PLUS_GEMS
        elif kind == "premium":
            if state["premium"]:
                raise PassError("Северо-Пасс++ уже куплен")
            price = (
                pass_config.PRICE_UPGRADE_GEMS
                if state["plus"]
                else pass_config.PRICE_PREMIUM_GEMS
            )
        elif kind == "upgrade":
            if not state["plus"]:
                raise PassError("Сначала купи Северо-Пасс+")
            if state["premium"]:
                raise PassError("Улучшение уже куплено")
            price = pass_config.PRICE_UPGRADE_GEMS
        else:
            raise PassError("Неизвестная покупка")

        async with self.pool.acquire() as con:
            async with con.transaction():
                paid = await con.fetchrow(
                    "update players set crystals = crystals - $2 "
                    "where user_id = $1 and crystals >= $2 returning crystals",
                    int(user_id),
                    int(price),
                )
                if paid is None:
                    raise PassError(f"Не хватает кристаллов: нужно {price}")
                if kind == "plus":
                    await con.execute(
                        "update pass_progress set plus = true, updated_at = now() "
                        "where user_id = $1 and season = $2",
                        int(user_id),
                        season,
                    )
                else:
                    boost = int(
                        pass_config.TOTAL_XP * pass_config.PREMIUM_BOOST
                    )
                    await con.execute(
                        """
                        update pass_progress
                           set plus = true,
                               premium = true,
                               xp = xp + $3,
                               updated_at = now()
                         where user_id = $1 and season = $2
                        """,
                        int(user_id),
                        season,
                        boost,
                    )
        if kind != "plus":
            await self._grant_skin(user_id)
        return {
            "paid": int(price),
            "boost": int(pass_config.TOTAL_XP * pass_config.PREMIUM_BOOST)
            if kind != "plus"
            else 0,
        }

    async def _grant_skin(self, user_id: int) -> None:
        """Сезонная карта-скин «Ученица Валерия» — один раз на аккаунт."""
        async with self.pool.acquire() as con:
            have = await con.fetchval(
                "select 1 from collection where user_id = $1 and card_id = $2",
                int(user_id),
                SKIN_CARD,
            )
            if have:
                return
            await con.execute(
                "insert into collection (user_id, card_id, count) values ($1, $2, 1) "
                "on conflict (user_id, card_id) do update set count = collection.count + 1",
                int(user_id),
                SKIN_CARD,
            )

    async def ensure_title(self, user_id: int, season: str | None = None) -> str | None:
        """Титул сезона за полное прохождение сп++ (50 уровней)."""
        season = season or pass_config.season_key()
        async with self.pool.acquire() as con:
            row = await con.fetchrow(
                "select xp, premium from pass_progress where user_id = $1 and season = $2",
                int(user_id),
                season,
            )
            if row is None or not row["premium"]:
                return None
            if pass_config.level_for(int(row["xp"] or 0)) < pass_config.LEVELS:
                return None
            theme = pass_config.theme()
            title = str(theme.get("title") or "Лучший из лучших")
            code = "pass:" + season
            have = await con.fetchval(
                "select 1 from player_titles where user_id = $1 and code = $2",
                int(user_id),
                code,
            )
            if not have:
                await con.execute(
                    "insert into player_titles (user_id, code, title, season, glow) "
                    "values ($1, $2, $3, $4, true)",
                    int(user_id),
                    code,
                    title,
                    season,
                )
        return title

    # ------------------------------------------------------------------ #
    # Конец сезона
    # ------------------------------------------------------------------ #

    async def close_old_seasons(self, user_id: int) -> list[dict[str, Any]]:
        """Закрывает прошлые сезоны: авто-выдаёт незабранное и пишет отчёт."""
        current = pass_config.season_key()
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                "select * from pass_progress where user_id = $1 and season < $2",
                int(user_id),
                current,
            )
        reports: list[dict[str, Any]] = []
        for row in rows:
            season = str(row["season"])
            already = await self._reported(user_id, season)
            if already:
                continue
            report = await self._close_one(user_id, row)
            reports.append(report)
        return reports

    async def _reported(self, user_id: int, season: str) -> bool:
        async with self.pool.acquire() as con:
            return bool(
                await con.fetchval(
                    "select 1 from pass_reports where user_id = $1 and season = $2",
                    int(user_id),
                    season,
                )
            )

    async def _close_one(self, user_id: int, row: Any) -> dict[str, Any]:
        season = str(row["season"])
        xp = int(row["xp"] or 0)
        level = pass_config.level_for(xp)
        plus = bool(row["plus"])
        premium = bool(row["premium"])
        claimed_free = {int(x) for x in self._json(row["claimed_free"])}
        claimed_plus = {int(x) for x in self._json(row["claimed_plus"])}
        claimed_prem = {int(x) for x in self._json(row["claimed_prem"])}
        granted: list[str] = []
        async with self.pool.acquire() as con:
            async with con.transaction():
                for number in range(1, level + 1):
                    reward = pass_rewards.level(season, number)
                    if reward is None:
                        continue
                    tracks = [("free", reward["free"], claimed_free)]
                    if plus:
                        tracks.append(("plus", reward["plus"], claimed_plus))
                    if premium and reward.get("premium") is not None:
                        tracks.append(("premium", reward["premium"], claimed_prem))
                    for track, bundle, done in tracks:
                        if bundle is None or number in done:
                            continue
                        part = await bundles.grant(self.db, con, int(user_id), bundle)
                        granted.extend(part)
                        done.add(number)
                await con.execute(
                    """
                    update pass_progress
                       set claimed_free = $3::jsonb,
                           claimed_plus = $4::jsonb,
                           claimed_prem = $5::jsonb,
                           updated_at = now()
                     where user_id = $1 and season = $2
                    """,
                    int(user_id),
                    season,
                    json.dumps(sorted(claimed_free)),
                    json.dumps(sorted(claimed_plus)),
                    json.dumps(sorted(claimed_prem)),
                )
                payload = {
                    "season": season,
                    "level": level,
                    "plus": plus,
                    "premium": premium,
                    "items": granted[-40:],
                    "count": len(granted),
                }
                await con.execute(
                    "insert into pass_reports (user_id, season, payload) "
                    "values ($1, $2, $3::jsonb)",
                    int(user_id),
                    season,
                    json.dumps(payload),
                )
        return payload

    async def unseen_reports(self, user_id: int, mark_seen: bool = True) -> list[dict[str, Any]]:
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                "select id, season, payload from pass_reports "
                "where user_id = $1 and not seen order by id desc",
                int(user_id),
            )
            if rows and mark_seen:
                await con.execute(
                    "update pass_reports set seen = true where user_id = $1 and not seen",
                    int(user_id),
                )
        out: list[dict[str, Any]] = []
        for row in rows:
            payload = row["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload or "{}")
            out.append(payload)
        return out

    # ------------------------------------------------------------------ #
    # Бонусы после 50 уровня
    # ------------------------------------------------------------------ #

    async def bonus_state(self, user_id: int, season: str | None = None) -> dict[str, Any]:
        state = await self.progress(user_id, season)
        return {
            "steps": state["bonus_steps"],
            "claimed": state["bonus_claimed"],
            "picks": state["bonus_picks"],
            "left": max(0, state["bonus_steps"] - state["bonus_claimed"]),
            "to_next": pass_config.bonus_left(state["xp"]),
        }

    async def claim_bonus(
        self, user_id: int, step: int, index: int, season: str | None = None
    ) -> dict[str, Any]:
        season = season or pass_config.season_key()
        step = int(step)
        index = int(index)
        if index not in (1, 2):
            raise PassError("Неизвестный вариант награды")
        state = await self.progress(user_id, season)
        if step < 1 or step > state["bonus_steps"]:
            raise PassError("Этот бонус ещё не заработан")
        if index == 1 and step <= state["bonus_claimed"]:
            raise PassError("Бонус уже забран")
        if any(int(p.get("step", 0)) == step and int(p.get("index", 0)) == index
               for p in state["bonus_picks"]):
            raise PassError("Этот вариант уже забран")
        options = pass_rewards.bonus_choices(season, step)
        option = next(item for item in options if int(item["index"]) == index)
        price = int(option["gems"])
        async with self.pool.acquire() as con:
            async with con.transaction():
                if price:
                    paid = await con.fetchrow(
                        "update players set crystals = crystals - $2 "
                        "where user_id = $1 and crystals >= $2 returning crystals",
                        int(user_id),
                        price,
                    )
                    if paid is None:
                        raise PassError(f"Не хватает кристаллов: нужно {price}")
                await con.execute(
                    """
                    update pass_progress
                       set bonus_claimed = greatest(bonus_claimed, $3),
                           bonus_picks = bonus_picks || $4::jsonb,
                           updated_at = now()
                     where user_id = $1 and season = $2
                    """,
                    int(user_id),
                    season,
                    step if index == 1 else state["bonus_claimed"],
                    json.dumps([{"step": step, "index": index}]),
                )
                granted = await bundles.grant(
                    self.db, con, int(user_id), option["bundle"]
                )
        return {"granted": granted, "step": step, "index": index, "paid": price}

    # ------------------------------------------------------------------ #
    # Награды уровней
    # ------------------------------------------------------------------ #

    async def claim_level(self, user_id: int, level: int, track: str) -> dict[str, Any]:
        season = pass_config.season_key()
        state = await self.progress(user_id, season)
        row = pass_rewards.level(season, level)
        if row is None:
            raise PassError("Такого уровня нет")
        if int(level) > state["level"]:
            raise PassError("Уровень ещё не открыт")
        column = {"free": "claimed_free", "plus": "claimed_plus", "premium": "claimed_prem"}.get(
            track
        )
        if column is None:
            raise PassError("Неизвестная дорожка")
        if track == "plus" and not state["plus"]:
            raise PassError("Нужен Северо-Пасс+")
        if track == "premium" and not state["premium"]:
            raise PassError("Нужен Северо-Пасс++")
        bundle = row.get(track)
        if bundle is None:
            raise PassError("На этом уровне нет награды этой дорожки")
        if int(level) in state[column]:
            raise PassError("Награда уже забрана")
        async with self.pool.acquire() as con:
            async with con.transaction():
                await con.execute(
                    f"update pass_progress set {column} = {column} || $3::jsonb, "
                    "updated_at = now() where user_id = $1 and season = $2",
                    int(user_id),
                    season,
                    json.dumps([int(level)]),
                )
                granted = await bundles.grant(self.db, con, int(user_id), bundle)
        await self.ensure_title(user_id, season)
        return {"granted": granted, "level": int(level), "track": track}
