from app.cards import CARDS
from app.rewards import STAKE_PERCENT, battle_reward, total_score


def test_percent_is_five():
    assert STAKE_PERCENT == 5


def test_stake_is_five_percent_of_card_points():
    assert battle_reward(10000) == 500
    assert battle_reward(15000) == 750
    assert battle_reward(250) == 12  # 12.5 округляется вниз
    assert battle_reward(0) == 0
    assert battle_reward(-100) == 0


def test_stake_is_always_smaller_than_the_card():
    for card in CARDS:
        stake = battle_reward(card.points)
        assert 0 < stake < card.points, card.card_id


def test_total_score_never_goes_negative():
    assert total_score(1000, -300) == 700
    assert total_score(1000, 250) == 1250
    assert total_score(100, -500) == 0
