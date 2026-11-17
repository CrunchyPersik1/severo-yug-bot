
"""Промокоды из базы: любой набор наград, общий тираж, точный срок.

Формат кода — латиница в нижнем регистре, без пробелов и дефисов.
Награда хранится словарём bundles + необязательные особые поля:
  pass_plus, pass_premium, title  (строка-подпись титула)
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from . import bundles, pass_config

CODE_RE = re.compile(r"^[a-z0-9]{3,24}$")
BUNDLE_KEYS = (
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


class PromoCodeError(Exception):
    """Ошибку можно показать игроку."""


class PromoRepo:
    def __init__(self, db: Any) -> None:
        self.db = db

    @property
    def pool(self):
        return self.db._p()

    # ------------------------------------------------------------------ #

    @staticmethod
    def normalize(raw: str) -> str:
        return re.sub(r"[^a-z0-9]", "", (raw or "").strip().lower())

    async def create(
        self,
        code: str,
        payload: dict[str, Any],
        uses_total: int = 1,
        expires_at: datetime | None = None,
        note: str = "",
        created_by: int | None = None,
    ) -> dict[str, Any]:
        clean = self.normalize(code)
        if not CODE_RE.match(clean):
            raise PromoCodeError("Код: 3-24 символа, только латиница и цифры")
        if int(uses_total) < 1:
            raise PromoCodeError("Тираж должен быть хотя бы 1")
        if not payload:
            raise PromoCodeError("Пустая награда")
        async with self.pool.acquire() as con:
            exists = await con.fetchval(
                "select 1 from promo_codes where code = $1", clean
            )
            if exists:
                raise PromoCodeError("Такой код уже есть")
            await con.execute(
                """
                insert into promo_codes
                    (code, payload, note, uses_total, expires_at, created_by)
                values ($1, $2::jsonb, $3, $4, $5, $6)
                """,
                clean,
                json.dumps(payload),
                note,
                int(uses_total),
                expires_at,
                created_by,
            )
        return {"code": clean, "uses_total": int(uses_total), "expires_at": expires_at}

    async def deactivate(self, code: str) -> bool:
        clean = self.normalize(code)
        async with self.pool.acquire() as con:
            row = await con.fetchrow(
                "update promo_codes set active = false where code = $1 returning code",
                clean,
            )
        return row is not None

    async def list(self, limit: int = 20) -> list[dict[str, Any]]:
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                "select code, payload, note, uses_total, uses_done, expires_at, active "
                "from promo_codes order by created_at desc limit $1",
                int(limit),
            )
        return [
            {
                "code": row["code"],
                "payload": row["payload"],
                "note": row["note"],
                "uses_total": int(row["uses_total"]),
                "uses_done": int(row["uses_done"]),
                "expires_at": row["expires_at"],
                "active": bool(row["active"]),
            }
            for row in rows
        ]

    async def redeem(self, user_id: int, raw: str) -> dict[str, Any] | None:
        """Активирует код. None — если такого кода в базе нет."""
        clean = self.normalize(raw)
        if not clean:
            return None
        async with self.pool.acquire() as con:
            async with con.transaction():
                row = await con.fetchrow(
                    "select * from promo_codes where code = $1 for update", clean
                )
                if row is None:
                    return None
                if not row["active"]:
                    raise PromoCodeError("Код больше не действует")
                expires = row["expires_at"]
                if expires is not None and expires < datetime.now(timezone.utc):
                    raise PromoCodeError("Срок действия кода истёк")
                if int(row["uses_done"]) >= int(row["uses_total"]):
                    raise PromoCodeError("Тираж кода закончился")
                already = await con.fetchval(
                    "select 1 from promo_activations where code = $1 and user_id = $2",
                    clean,
                    int(user_id),
                )
                if already:
                    raise PromoCodeError("Ты уже активировал этот код")
                await con.execute(
                    "insert into promo_activations (code, user_id) values ($1, $2)",
                    clean,
                    int(user_id),
                )
                await con.execute(
                    "update promo_codes set uses_done = uses_done + 1 where code = $1",
                    clean,
                )
                payload = row["payload"]
                if isinstance(payload, str):
                    payload = json.loads(payload or "{}")
                bundle = {
                    key: int(payload.get(key) or 0)
                    for key in BUNDLE_KEYS
                    if int(payload.get(key) or 0)
                }
                bundle["cards"] = [str(card) for card in payload.get("cards") or []]
                if payload.get("weapon"):
                    bundle["weapon"] = str(payload["weapon"])
                granted: list[str] = []
                if bundle:
                    granted += await bundles.grant(
                        self.db, con, int(user_id), bundles.make(**bundle)
                    )
                if payload.get("pass_plus") or payload.get("pass_premium"):
                    season = pass_config.season_key()
                    await con.execute(
                        """
                        insert into pass_progress (user_id, season, plus, premium)
                        values ($1, $2, true, $3)
                        on conflict (user_id, season) do update
                           set plus = true,
                               premium = pass_progress.premium or $3,
                               updated_at = now()
                        """,
                        int(user_id),
                        season,
                        bool(payload.get("pass_premium")),
                    )
                    granted.append("Северо-Пасс+")
                if payload.get("title"):
                    await con.execute(
                        "insert into player_titles (user_id, code, title, season, glow) "
                        "values ($1, $2, $3, $4, true)",
                        int(user_id),
                        clean,
                        str(payload["title"]),
                        payload.get("season"),
                    )
                    granted.append("титул «" + str(payload["title"]) + "»")
        return {"code": clean, "granted": granted, "note": row["note"]}
