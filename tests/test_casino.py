"""Казино: вероятности, выплаты и модификаторы карт."""

import random

from app import casino


def test_green_is_about_one_in_fifty():
    rng = random.Random(11)
    rolls = [casino.roll_color(rng) for _ in range(200_000)]
    total = len(rolls)
    assert abs(rolls.count("green") / total - 0.02) < 0.003
    assert abs(rolls.count("red") / total - 0.49) < 0.01
    assert abs(rolls.count("black") / total - 0.49) < 0.01


def test_win_multipliers():
    assert casino.points_win(1000, "red") == 2000
    assert casino.points_win(1000, "black") == 2000
    assert casino.points_win(1000, "green") == 5000


def test_loss_returns_a_third():
    assert casino.points_lose(1000) == 333
    assert casino.points_lose(300) == 100


def test_card_fate_is_one_in_five_deletions():
    rng = random.Random(3)
    fates = [casino.card_fate(rng) for _ in range(20_000)]
    assert abs(fates.count("delete") / len(fates) - 0.20) < 0.02


def test_casino_bonus_stacks_and_has_a_floor():
    assert casino.apply_bonus({}, {"atk": 15}) == {"atk": 15}
    assert casino.apply_bonus({"atk": 10}, {"atk": 5}) == {"atk": 15}
    assert casino.apply_bonus({"atk": -40}, {"atk": -30}) == {"atk": -50}


def test_win_and_lose_steps_are_positive_and_negative():
    rng = random.Random(5)
    for _ in range(200):
        assert sum(casino.random_win_bonus(rng).values()) > 0
        assert sum(casino.random_lose_bonus(rng).values()) < 0


def test_only_rare_cards_can_be_bought_back():
    assert casino.can_buyback("ultra")
    assert casino.can_buyback("secret")
    assert casino.can_buyback("legendary")
    assert not casino.can_buyback("epic")
    assert not casino.can_buyback("rare")


def test_max_bonus_is_reachable():
    assert casino.MAX_BONUS == {"atk": 30, "hp": 30, "def": 30}
