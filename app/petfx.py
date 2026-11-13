"""Пассивные эффекты надетого пета.

Один пет на игрока: сервер берёт его эффект и подмешивает в свои расчёты.
Здесь только чтение состояния и множители — никакой выдачи наград.
"""

from __future__ import annotations

from typing import Any

from . import pets


async def equipped(db: Any, user_id: int) -> dict[str, Any] | None:
    row = await db.equipped_pet(int(user_id))
    if not row:
        return None
    pet = pets.get(row["pet_id"])
    if pet is None:
        return None
    return {"id": pet.id, "kind": pet.kind, "level": int(row["level"]),
            "effect": pet.effect(row["level"]), "name": pet.name}


async def multi(db: Any, user_id: int) -> dict[str, float]:
    """{"gems": 0.25, "double_drop": 0.10, ...} для надетого пета."""
    current = await equipped(db, user_id)
    return {current["kind"]: current["effect"]} if current else {}


def scale(base: float, effect: float) -> float:
    """Базовое число с бонусом пета: 100 * (1 + 0.25)."""
    return float(base) * (1.0 + max(0.0, float(effect)))


def bonus_points(bundle: dict[str, Any], effect: float) -> dict[str, Any]:
    """Поднимает очки и Юги в наборе награды, не трогая штучные призы."""
    if effect <= 0:
        return bundle
    out = dict(bundle)
    for key in ("points", "yugi"):
        if out.get(key):
            out[key] = int(round(int(out[key]) * (1.0 + effect)))
    return out
