import random

from app.battle import (
    ACTION_ABILITY,
    ACTION_HIT,
    KEY_A,
    KEY_B,
    apply_action,
    can_use_ability,
    new_state,
    other,
    side_for_user,
    surrender,
)
from app.cards import CARDS, get_card


def make_state(card_a: str = "oleg", card_b: str = "oleg", first: str = KEY_A):
    state = new_state(get_card(card_a), get_card(card_b), first=first)
    state["sides"][KEY_A]["user_id"] = 1
    state["sides"][KEY_B]["user_id"] = 2
    return state


def test_strike_reduces_hp():
    state = make_state()
    out = apply_action(state, KEY_A, ACTION_HIT)
    assert out["ok"]
    assert state["sides"][KEY_B]["hp"] == get_card("oleg").hp - get_card("oleg").atk
    assert state["turn"] == KEY_B


def test_only_turn_owner_can_act():
    state = make_state()
    out = apply_action(state, KEY_B, ACTION_HIT)
    assert out["ok"] is False
    assert "ход" in out["error"].lower()


def test_shield_absorbs_damage():
    state = make_state("tamerlan_mif", "oleg")
    apply_action(state, KEY_A, ACTION_ABILITY)  # щит 25
    assert state["sides"][KEY_A]["shield"] == 25
    apply_action(state, KEY_B, ACTION_HIT)  # 10 урона в щит
    assert state["sides"][KEY_A]["shield"] == 15
    assert state["sides"][KEY_A]["hp"] == get_card("tamerlan_mif").hp


def test_ignore_shield_passes_through():
    state = make_state("karina", "tamerlan_mif")
    apply_action(state, KEY_A, ACTION_HIT)
    apply_action(state, KEY_B, ACTION_ABILITY)  # щит 25
    before_hp = state["sides"][KEY_B]["hp"]
    apply_action(state, KEY_A, ACTION_ABILITY)  # точный удар 10 сквозь щит
    assert state["sides"][KEY_B]["hp"] == before_hp - 10
    assert state["sides"][KEY_B]["shield"] == 25


def test_dodge_negates_one_action():
    state = make_state("evita", "oleg")
    apply_action(state, KEY_A, ACTION_ABILITY)  # dodge 1 + damage 8
    assert state["sides"][KEY_A]["dodge"] == 1
    hp_before = state["sides"][KEY_A]["hp"]
    apply_action(state, KEY_B, ACTION_HIT)
    assert state["sides"][KEY_A]["hp"] == hp_before
    assert state["sides"][KEY_A]["dodge"] == 0


def test_poison_ticks_when_victim_turn_starts():
    state = make_state("amir_1", "oleg")
    oleg_hp = state["sides"][KEY_B]["hp"]
    apply_action(state, KEY_A, ACTION_ABILITY)  # 8 урона + яд 6 на 2 хода
    # яд уже тикнул в начале хода B
    assert state["sides"][KEY_B]["hp"] == oleg_hp - 14
    assert state["sides"][KEY_B]["poison_turns"] == 1
    apply_action(state, KEY_B, ACTION_HIT)
    apply_action(state, KEY_A, ACTION_HIT)
    assert state["sides"][KEY_B]["poison_turns"] == 0


def test_stun_skips_turn():
    state = make_state("elizaveta", "oleg")
    hp_a = state["sides"][KEY_A]["hp"]
    apply_action(state, KEY_A, ACTION_ABILITY)  # оглушение B
    # ход B пропущен сразу же, ход вернулся к A
    assert state["sides"][KEY_B]["stun"] == 0
    assert state["sides"][KEY_A]["hp"] == hp_a
    assert state["turn"] == KEY_A
    assert any("Оглушён" in entry for entry in state["log"])


def test_ability_cooldown_blocks_reuse():
    state = make_state("azat", "oleg")
    apply_action(state, KEY_A, ACTION_ABILITY)
    assert state["sides"][KEY_A]["cd"] == get_card("azat").ability.cooldown
    assert can_use_ability(state["sides"][KEY_A]) is False
    apply_action(state, KEY_B, ACTION_HIT)
    apply_action(state, KEY_A, ACTION_ABILITY)  # ещё кд -> обычный удар
    assert state["sides"][KEY_A]["cd"] == 1


def test_counter_damages_attacker():
    state = make_state("milana", "oleg")
    apply_action(state, KEY_A, ACTION_ABILITY)  # dodge 1 + counter 10
    assert state["sides"][KEY_A]["counter"] == 10
    hp_attacker = state["sides"][KEY_B]["hp"]
    apply_action(state, KEY_B, ACTION_HIT)
    assert state["sides"][KEY_B]["hp"] < hp_attacker


def test_cleanse_removes_poison():
    state = make_state("rafael", "amir_1")
    apply_action(state, KEY_A, ACTION_HIT)
    apply_action(state, KEY_B, ACTION_ABILITY)  # яд
    assert state["sides"][KEY_A]["poison_turns"] > 0
    apply_action(state, KEY_A, ACTION_ABILITY)  # heal + cleanse
    assert state["sides"][KEY_A]["poison_turns"] == 0


def test_steal_heals_self():
    state = make_state("amiliya_secret", "oleg")
    state["sides"][KEY_A]["hp"] = 30
    apply_action(state, KEY_A, ACTION_ABILITY)
    assert state["sides"][KEY_A]["hp"] == 45
    assert state["sides"][KEY_B]["hp"] == get_card("oleg").hp - 15


def test_self_stun_penalty():
    state = make_state("timur_secret", "oleg")
    hp_b = state["sides"][KEY_B]["hp"]
    apply_action(state, KEY_A, ACTION_ABILITY)  # 20 урона, но свой ход пропущен
    assert state["sides"][KEY_B]["hp"] == hp_b - 20
    assert state["turn"] == KEY_B
    apply_action(state, KEY_B, ACTION_HIT)
    # ход должен был перейти к A, но A оглушён -> снова B
    assert state["turn"] == KEY_B
    assert state["sides"][KEY_A]["stun"] == 0


def test_turn_limit_is_a_draw():
    state = make_state("tamerlan_mif", "glafira")
    guard = 0
    while not state["over"] and guard < 200:
        apply_action(state, state["turn"], ACTION_HIT, max_turns=10)
        guard += 1
    assert state["over"]
    assert state["winner"] == "draw"
    assert state["reason"] == "turn_limit"


def test_timeout_forfeit():
    state = make_state()
    # игрок A трижды не нажал кнопку -> техническое поражение
    for _ in range(3):
        state["turn"] = KEY_A
        apply_action(state, KEY_A, ACTION_HIT, max_timeouts=3, register_timeout=True)
    assert state["over"]
    assert state["winner"] == KEY_B
    assert state["reason"] == "timeout"


def test_surrender():
    state = make_state()
    surrender(state, KEY_A)
    assert state["over"] and state["winner"] == KEY_B


def test_side_for_user():
    state = make_state()
    assert side_for_user(state, 1) == KEY_A
    assert side_for_user(state, 2) == KEY_B
    assert side_for_user(state, 99) is None


def test_every_card_ability_is_resolvable():
    for card in CARDS:
        for action in (ACTION_HIT, ACTION_ABILITY):
            state = make_state(card.card_id, "oleg")
            out = apply_action(state, KEY_A, action)
            assert out["ok"], f"{card.card_id} {action}"


def test_random_battles_always_terminate():
    rng = random.Random(2026)
    for _ in range(400):
        a, b = rng.choice(CARDS).card_id, rng.choice(CARDS).card_id
        state = make_state(a, b, first=rng.choice([KEY_A, KEY_B]))
        actions = 0
        while not state["over"] and actions < 200:
            actor = state["turn"]
            action = rng.choice([ACTION_HIT, ACTION_ABILITY, ACTION_ABILITY])
            out = apply_action(state, actor, action, max_turns=30)
            assert out["ok"], (a, b, out)
            actions += 1
        assert state["over"], (a, b)
        assert state["winner"] in (KEY_A, KEY_B, "draw")
        assert state["sides"][KEY_A]["hp"] <= state["sides"][KEY_A]["max_hp"]


def test_no_negative_hp_leak_or_overheal():
    state = make_state("valeriya", "konstantin")
    while not state["over"]:
        apply_action(state, state["turn"], ACTION_ABILITY if False else ACTION_HIT)
    for key in (KEY_A, KEY_B):
        side = state["sides"][key]
        assert side["hp"] <= side["max_hp"]

def test_trofim_new_ability_is_choking_grip():
    card = get_card("trofim")
    assert card.ability.name == "Удушающая"
    assert card.ability.effects == {"damage": 12, "silence": 1}


def test_emin_steals_and_applies_permanent_drain():
    state = make_state("emin", "oleg")
    emin = state["sides"][KEY_A]
    oleg = state["sides"][KEY_B]
    emin["hp"] = 50
    oleg_hp = oleg["hp"]
    apply_action(state, KEY_A, ACTION_ABILITY)
    # 50 + 8 украденных. Заклинание тут же тикнуло: ещё +1, а Олегу −1
    assert emin["hp"] == 59, "отжал 8 HP и вылечил себя"
    assert oleg["hp"] == oleg_hp - 9
    assert oleg["drain"] == 1 and oleg["drain_from"] == KEY_A


def test_drain_ticks_on_every_turn_of_the_victim():
    state = make_state("emin", "oleg")
    emin = state["sides"][KEY_A]
    oleg = state["sides"][KEY_B]
    emin["hp"] = 50
    apply_action(state, KEY_A, ACTION_ABILITY)

    apply_action(state, KEY_B, ACTION_HIT)  # Олег бьёт, ход переходит к Эмину
    emin_before = emin["hp"]
    oleg_before = oleg["hp"]

    apply_action(state, KEY_A, ACTION_HIT)  # Эмин бьёт → начинается ход Олега
    assert oleg["hp"] == oleg_before - get_card("emin").atk - 1, "утечка тикает каждый ход"
    assert emin["hp"] == emin_before + 1, "украденное уходит Эмину"


def test_drain_is_removed_when_owner_dies():
    state = make_state("emin", "oleg")
    apply_action(state, KEY_A, ACTION_ABILITY)
    assert state["sides"][KEY_B]["drain"] == 1
    state["sides"][KEY_A]["hp"] = 0
    apply_action(state, KEY_B, ACTION_HIT)
    assert state["sides"][KEY_B]["drain"] == 0
    assert state["sides"][KEY_B]["drain_from"] is None


def test_new_secret_cards_exist():
    for card_id in ("daniel_sult", "saida", "artem"):
        card = get_card(card_id)
        assert card.rarity == "secret"
        assert card.points == 11000
        assert card.budget >= 195

def test_no_turn_limit_by_default():
    """Без лимита бой не должен закончиться ничьей сам по себе."""
    state = make_state("valeriya", "tamerlan_mif")
    state["sides"][KEY_A]["hp"] = 100000
    state["sides"][KEY_B]["hp"] = 100000
    state["sides"][KEY_A]["max_hp"] = 100000
    state["sides"][KEY_B]["max_hp"] = 100000
    for _ in range(120):
        if state["over"]:
            break
        apply_action(state, state["turn"], ACTION_HIT)
    assert not state["over"], "бой не должен прерываться лимитом"
    assert state["turn_no"] > 30


def test_explicit_turn_limit_still_works():
    state = make_state("valeriya", "tamerlan_mif")
    state["sides"][KEY_A]["hp"] = 100000
    state["sides"][KEY_B]["hp"] = 100000
    state["sides"][KEY_A]["max_hp"] = 100000
    state["sides"][KEY_B]["max_hp"] = 100000
    for _ in range(40):
        if state["over"]:
            break
        apply_action(state, state["turn"], ACTION_HIT, max_turns=5)
    assert state["over"] and state["reason"] == "turn_limit"
