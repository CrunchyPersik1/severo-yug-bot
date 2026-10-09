"""Пампы: расписание, вершина и шаги."""

import random

from app import pumps


def test_next_delay_is_about_an_hour():
    rng = random.Random(1)
    for _ in range(50):
        minutes = pumps.next_delay(rng).total_seconds() / 60
        assert 25 <= minutes <= 75


def test_peak_price_is_plus_100_to_400_percent():
    rng = random.Random(2)
    for _ in range(200):
        peak = pumps.peak_price(1000, 1_000_000, rng)
        assert 2000 <= peak <= 5000


def test_peak_price_never_beats_the_ceiling():
    assert pumps.peak_price(1000, 1500) == 1500


def test_steps_go_up_and_come_back():
    price = 1000
    for _ in range(60):
        price = pumps.step_up(price, 5000)
    assert price == 5000
    for _ in range(60):
        price = pumps.step_down(price, 1000)
    assert price == 1000


def test_has_room_at_the_ceiling():
    assert pumps.has_room(1000, 1000, 6.0)
    assert not pumps.has_room(6000, 1000, 6.0)
