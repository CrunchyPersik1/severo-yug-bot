"""Рейд-босс: полоска, проценты и математика ударов."""

from app import boss


def test_bar_fills_proportionally():
    assert boss.bar(15_000, 15_000).count("🟩") == 12
    assert boss.bar(0, 15_000).count("🟩") == 0
    half = boss.bar(7_500, 15_000)
    assert half.count("🟩") == 6
    assert half.count("⬛") == 6


def test_percent_edges():
    assert boss.percent(15_000, 15_000) == 100
    assert boss.percent(0, 15_000) == 0
    assert boss.percent(15_000, 0) == 0


def test_default_boss_dies_in_three_hundred_hits():
    assert boss.DEFAULT_HP // boss.HIT_DAMAGE == 300
