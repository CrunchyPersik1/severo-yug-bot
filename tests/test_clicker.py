"""Кликер: шансы и награды."""

import random
from collections import Counter

from app import clicker


def test_weights_sum_to_one_and_points_dominate():
    total = sum(clicker.WEIGHTS.values())
    assert abs(total - 1.0) < 1e-9
    assert clicker.WEIGHTS[clicker.POINTS] > 0.9
    for kind in (clicker.DROP, clicker.SPIN, clicker.CASE, clicker.CARD):
        assert clicker.WEIGHTS[kind] < 0.01, kind


def test_roll_reward_is_mostly_points():
    rng = random.Random(3)
    rolls = Counter(clicker.roll_reward(rng)[0] for _ in range(20_000))
    assert rolls[clicker.POINTS] / 20_000 > 0.85
    assert set(rolls) <= set(clicker.WEIGHTS)


def test_points_are_small():
    rng = random.Random(4)
    for _ in range(200):
        kind, value = clicker.roll_reward(rng)
        if kind == clicker.POINTS:
            assert clicker.POINTS_MIN <= int(value) <= clicker.POINTS_MAX


def test_card_reward_is_a_card():
    rng = random.Random(5)
    for _ in range(3000):
        kind, value = clicker.roll_reward(rng)
        if kind == clicker.CARD:
            assert getattr(value, "card_id", None)
            break
    else:
        raise AssertionError("карта ни разу не выпала")
