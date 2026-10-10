"""Командный PvP: по 2-3 карты на игрока, команды по двое.

Состояние полностью сериализуемо и живёт в таблице battles, поэтому перезапуск
Render бой не ломает. Механика ходов как в Angry Birds Epic: каждой карте нужно
сходить, раунд заканчивается, когда походили все.
"""

from __future__ import annotations

import random
from typing import Any

from .battle import (
    _apply_ability,
    _end_turn,
    _log,
    _strike,
    begin_unit_turn,
    can_use_ability,
    new_side,
)
from .cards import get_card

TEAM_RED = "red"
TEAM_BLUE = "blue"
TEAMS = (TEAM_RED, TEAM_BLUE)

MAX_CARDS = 3
TIMEOUT_DAMAGE = 15
TIMEOUT_SECONDS = 60

ACTION_HIT = "hit"
ACTION_ABILITY = "ability"


def build_state(participants: list[dict[str, Any]], picks: dict[int, list[dict]], first_user_id: int) -> dict[str, Any]:
    """participants: [{'user_id','name','team'}], picks: {user_id: [{'card','stats'}]}."""
    sides: dict[str, Any] = {}
    teams: dict[str, list[str]] = {TEAM_RED: [], TEAM_BLUE: []}
    order: list[int] = []
    index = 0
    for person in participants:
        order.append(person["user_id"])
        for entry in picks.get(person["user_id"], []):
            index += 1
            key = f"u{index}"
            side = new_side(person["user_id"], entry["card"], entry.get("stats"))
            side["team"] = person["team"]
            side["name"] = person["name"]
            side["acted"] = False
            side["slot"] = index
            sides[key] = side
            teams[person["team"]].append(key)
    first = first_user_id if first_user_id in order else order[0]
    return {
        "mode": "team",
        "sides": sides,
        "teams": teams,
        "order": order,
        # Держим состав в состоянии: по нему считаем итоги и рисуем шапку боя.
        "participants": participants,
        "turn": first,
        "round": 1,
        "log": [],
        "over": False,
        "winner": None,
        "timeouts": {uid: 0 for uid in order},
    }


def unit_keys(state: dict[str, Any], user_id: int) -> list[str]:
    return [key for key, side in state["sides"].items() if side["user_id"] == user_id]


def is_alive(state: dict[str, Any], key: str) -> bool:
    return state["sides"][key]["hp"] > 0


def available(state: dict[str, Any], user_id: int) -> list[str]:
    return [
        key
        for key in unit_keys(state, user_id)
        if is_alive(state, key) and not state["sides"][key]["acted"]
    ]


def team_keys(state: dict[str, Any], team: str) -> list[str]:
    return list(state["teams"].get(team, []))


def team_alive(state: dict[str, Any], team: str) -> bool:
    return any(is_alive(state, key) for key in team_keys(state, team))


def enemy_team(team: str) -> str:
    return TEAM_BLUE if team == TEAM_RED else TEAM_RED


def check_over(state: dict[str, Any]) -> bool:
    red = team_alive(state, TEAM_RED)
    blue = team_alive(state, TEAM_BLUE)
    if red and blue:
        return False
    state["over"] = True
    state["winner"] = None if not (red or blue) else (TEAM_RED if red else TEAM_BLUE)
    return True


def begin_round(state: dict[str, Any]) -> None:
    for side in state["sides"].values():
        side["acted"] = False
        # способности восстанавливаются раз в раунд — раньше не восстанавливались
        side["cd"] = max(0, side["cd"] - 1)
        side["silence"] = max(0, side["silence"] - 1)
    state["round"] += 1
    _log(state, f"🔁 Раунд {state['round']}")


def advance(state: dict[str, Any]) -> None:
    """Передаёт ход следующему игроку, у кого остались неходившие карты."""
    if state["over"]:
        return
    order = state["order"]
    start = order.index(state["turn"]) if state["turn"] in order else -1
    for step in range(1, len(order) + 1):
        candidate = order[(start + step) % len(order)]
        if available(state, candidate):
            state["turn"] = candidate
            return
    begin_round(state)
    for candidate in order:
        if available(state, candidate):
            state["turn"] = candidate
            return


def activate(state: dict[str, Any], user_id: int, unit_key: str) -> dict[str, Any]:
    """Игрок выбрал карту. Возвращает статус: ready / skipped / finished."""
    if unit_key not in state["sides"]:
        return {"ok": False, "error": "Карта не найдена"}
    side = state["sides"][unit_key]
    if side["user_id"] != user_id:
        return {"ok": False, "error": "Это не твоя карта"}
    if state["turn"] != user_id:
        return {"ok": False, "error": "Сейчас не твой ход"}
    if not is_alive(state, unit_key):
        return {"ok": False, "error": "Эта карта уже уничтожена"}
    if side["acted"]:
        return {"ok": False, "error": "Эта карта уже ходила в этом раунде"}

    return {"ok": True, "status": "ready"}


def perform(
    state: dict[str, Any],
    user_id: int,
    unit_key: str,
    action: str = ACTION_HIT,
    target_key: str | None = None,
    ally_key: str | None = None,
) -> dict[str, Any]:
    """Выполняет ход выбранной картой и передаёт ход дальше."""
    side = state["sides"][unit_key]
    if side["user_id"] != user_id:
        return {"ok": False, "error": "Это не твоя карта"}
    if state["turn"] != user_id or side["acted"]:
        return {"ok": False, "error": "Этот ход уже сделан"}

    status = begin_unit_turn(state, unit_key, tick_cd=False)
    if status == "dead":
        side["acted"] = True
        if not check_over(state):
            advance(state)
        return {"ok": True, "skipped": True}
    if status == "skip":
        side["acted"] = True
        _end_turn(state, unit_key)
        if not check_over(state):
            advance(state)
        return {"ok": True, "skipped": True}

    card = get_card(side["card_id"])
    ally_key = ally_key or unit_key
    if action == ACTION_ABILITY and can_use_ability(side):
        _apply_ability(state, unit_key, card, foe_key=target_key, ally_key=ally_key)
    else:
        _strike(state, unit_key, card, foe_key=target_key)

    side["acted"] = True
    _end_turn(state, unit_key)
    if not check_over(state):
        advance(state)
    return {"ok": True}


def register_timeout(state: dict[str, Any], user_id: int) -> bool:
    """Игрок не ходит минуту: его карта получает 15 урона, ход идёт дальше."""
    if state["over"] or state["turn"] != user_id:
        return False
    keys = available(state, user_id) or [
        key for key in unit_keys(state, user_id) if is_alive(state, key)
    ]
    if not keys:
        return False
    victim = random.choice(keys)
    side = state["sides"][victim]
    side["hp"] -= TIMEOUT_DAMAGE
    state["timeouts"][user_id] = state["timeouts"].get(user_id, 0) + 1
    name = get_card(side["card_id"]).display_name
    _log(state, f"⏱ {side['name']} не ходит — {name} получает {TIMEOUT_DAMAGE} урона")
    if not check_over(state):
        advance(state)
    return True


def board(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Данные для отрисовки: карты по командам."""
    rows = []
    for team in TEAMS:
        for key in state["teams"].get(team, []):
            side = state["sides"][key]
            card = get_card(side["card_id"])
            rows.append(
                {
                    "key": key,
                    "team": team,
                    "name": side["name"],
                    "card": card,
                    "user_id": side["user_id"],
                    "hp": max(0, side["hp"]),
                    "max_hp": side["max_hp"],
                    "acted": side["acted"],
                    "alive": side["hp"] > 0,
                    "owner": side["user_id"],
                }
            )
    return rows
