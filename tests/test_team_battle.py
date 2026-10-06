"""Командный PvP: сборка боя, очередь ходов и победа."""

import random

from app.battle import new_side
from app.cards import get_card
from app import team_battle


def make_people():
    return [
        {"user_id": 1, "name": "Раз", "team": team_battle.TEAM_RED},
        {"user_id": 2, "name": "Два", "team": team_battle.TEAM_RED},
        {"user_id": 3, "name": "Три", "team": team_battle.TEAM_BLUE},
        {"user_id": 4, "name": "Четыре", "team": team_battle.TEAM_BLUE},
    ]


def make_picks(card_ids=("valeriya", "oleg")):
    return {
        uid: [{"card": get_card(card_ids[0])}, {"card": get_card(card_ids[1])}]
        for uid in (1, 2, 3, 4)
    }


def test_build_creates_two_units_per_player():
    state = team_battle.build_state(make_people(), make_picks(), 1)
    assert len(state["sides"]) == 8
    assert len(state["teams"][team_battle.TEAM_RED]) == 4
    assert len(state["teams"][team_battle.TEAM_BLUE]) == 4
    assert state["turn"] == 1


def test_every_unit_must_act_before_new_round():
    state = team_battle.build_state(make_people(), make_picks(), 1)
    order = []
    acted_units = []
    for _ in range(4):
        uid = state["turn"]
        order.append(uid)
        unit = team_battle.available(state, uid)[0]
        team_battle.activate(state, uid, unit)
        team_battle.perform(state, uid, unit, team_battle.ACTION_HIT, _enemy(state, unit))
        acted_units.append(unit)
    # за первые четыре хода каждый игрок походил ровно раз — одной из двух карт
    assert sorted(order) == [1, 2, 3, 4]
    assert state["round"] == 1
    assert all(state["sides"][key]["acted"] for key in acted_units)
    assert all(len(team_battle.available(state, uid)) == 1 for uid in (1, 2, 3, 4))


def _enemy(state, unit_key):
    side = state["sides"][unit_key]
    for key in state["teams"][team_battle.enemy_team(side["team"])]:
        if state["sides"][key]["hp"] > 0:
            return key
    return None


def test_round_advances_when_every_card_acted():
    state = team_battle.build_state(make_people(), make_picks(), 1)
    # 4 игрока по 2 карты — полный раунд это 8 ходов
    for _ in range(8):
        uid = state["turn"]
        unit = team_battle.available(state, uid)[0]
        team_battle.activate(state, uid, unit)
        team_battle.perform(state, uid, unit, team_battle.ACTION_HIT, _enemy(state, unit))
    assert state["round"] == 2
    assert len(team_battle.available(state, 1)) == 2, "в новом раунде обе карты снова готовы"


def test_team_loses_when_all_its_cards_die():
    state = team_battle.build_state(make_people(), make_picks(), 1)
    for key in state["teams"][team_battle.TEAM_BLUE]:
        state["sides"][key]["hp"] = 0
    assert team_battle.check_over(state)
    assert state["winner"] == team_battle.TEAM_RED


def test_healing_an_ally_does_not_touch_enemies():
    state = team_battle.build_state(make_people(), make_picks(("saida", "oleg")), 1)
    healer = team_battle.available(state, 1)[0]
    state["sides"][healer]["hp"] = 50
    team_battle.activate(state, 1, healer)
    enemy = _enemy(state, healer)
    enemy_hp = state["sides"][enemy]["hp"]
    team_battle.perform(state, 1, healer, team_battle.ACTION_ABILITY, enemy, healer)
    assert state["sides"][healer]["hp"] == 70
    assert state["sides"][enemy]["hp"] == enemy_hp


def test_timeout_hurts_the_slacker_and_passes_turn():
    state = team_battle.build_state(make_people(), make_picks(), 1)
    his = team_battle.unit_keys(state, 1)
    before = [state["sides"][key]["hp"] for key in his]
    assert team_battle.register_timeout(state, 1)
    after = [state["sides"][key]["hp"] for key in his]
    assert sum(before) - sum(after) == team_battle.TIMEOUT_DAMAGE
    assert state["turn"] != 1


def test_ownership_and_turn_are_enforced():
    state = team_battle.build_state(make_people(), make_picks(), 1)
    not_mine = team_battle.unit_keys(state, 3)[0]
    assert team_battle.activate(state, 1, not_mine)["ok"] is False
    assert team_battle.activate(state, 3, team_battle.unit_keys(state, 3)[0])["ok"] is False
