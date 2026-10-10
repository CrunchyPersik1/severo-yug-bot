"""Уровни: кривая опыта и награды."""

from app import levels


def test_curve_grows_and_caps():
    assert levels.xp_for_level(1) == 300
    assert levels.xp_for_level(99) > levels.xp_for_level(1)
    assert levels.level_from_xp(0) == 1
    assert levels.level_from_xp(299) == 1
    assert levels.level_from_xp(300) == 2
    assert levels.level_from_xp(10**9) == levels.MAX_LEVEL


def test_progress_inside_level():
    level, inside, need = levels.progress(300)
    assert level == 2
    assert inside == 0
    assert need == levels.xp_for_level(2)


def test_xp_amounts_match_spec():
    assert levels.XP_PER_CARD == 100
    assert levels.XP_CASINO_WIN == 3
    assert levels.XP_PURCHASE == 50
    assert levels.XP_SALE == 75


def test_first_75_are_light_and_last_25_are_rich():
    light = levels.rewards_for(40)
    assert light, "награда должна быть"
    assert all(
        reward["kind"] in {"points", "drops", "spins", "cases"} for reward in light
    )

    rich = levels.rewards_for(90)
    kinds = {reward["kind"] for reward in rich}
    assert {"drops", "shares", "card"} <= kinds
    points = sum(r["amount"] for r in rich if r["kind"] == "points")
    assert points > 20000, "на 90-м уже нормально сыпет"


def test_no_rewards_for_first_level():
    assert levels.rewards_for(1) == []
