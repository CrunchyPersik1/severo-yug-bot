"""Кристальная рулетка: шансы, призы и пачки спинов."""

import random

import pytest

from app import roulette


def test_crystal_weights_sum_to_one():
    total = sum(roulette.CRYSTAL_WEIGHTS.values())
    assert abs(total - 1.0) < 1e-9, total


def test_crystal_prizes_match_the_agreed_table():
    w = roulette.CRYSTAL_WEIGHTS
    assert w["crystals_10"] == 0.005
    assert w["crystals_5"] == 0.010
    assert w[roulette.PRIZE_CASE_D] == 0.01
    assert w[roulette.PRIZE_CASE_G] == 0.085


def test_crystal_distribution_matches_weights():
    rng = random.Random(7)
    seen: dict[str, int] = {}
    for _ in range(120_000):
        key = roulette.roll_crystal_prize(rng)["key"]
        seen[key] = seen.get(key, 0) + 1
    total = sum(seen.values())
    for key, weight in roulette.CRYSTAL_WEIGHTS.items():
        assert abs(seen.get(key, 0) / total - weight) < 0.01, key


def test_every_crystal_prize_has_a_label():
    rng = random.Random(3)
    keys = set()
    for _ in range(20_000):
        prize = roulette.roll_crystal_prize(rng)
        keys.add(prize["key"])
        assert prize["label"]
        assert prize["kind"] in {
            roulette.PRIZE_CRYSTALS,
            roulette.PRIZE_CASE_G,
            roulette.PRIZE_CASE_D,
            roulette.PRIZE_CASE_ULTRA,
            roulette.PRIZE_POINTS,
        }
    assert keys == set(roulette.CRYSTAL_WEIGHTS)


def test_crystals_come_in_10_and_5():
    found = {}
    rng = random.Random(11)
    while len(found) < 2:
        prize = roulette.roll_crystal_prize(rng)
        if prize["kind"] == roulette.PRIZE_CRYSTALS:
            found[prize["key"]] = prize["amount"]
    assert found == {"crystals_10": 10, "crystals_5": 5}


def test_crystal_points_stay_in_range():
    rng = random.Random(5)
    low = min(t[0] for t in roulette.CRYSTAL_POINT_TIERS)
    high = max(t[1] for t in roulette.CRYSTAL_POINT_TIERS)
    for _ in range(5000):
        prize = roulette.roll_crystal_prize(rng)
        if prize["kind"] == roulette.PRIZE_POINTS:
            assert low <= prize["amount"] <= high


def test_crystal_segments_match_weights():
    segments = roulette.crystal_segments()
    assert len(segments) == len(roulette.CRYSTAL_WEIGHTS)
    assert abs(sum(s["weight"] for s in segments) - 1.0) < 1e-9
    for seg in segments:
        assert seg["color"].startswith("#")
        assert seg["label"]


def test_two_kinds_only():
    assert roulette.KINDS == ("classic", "crystal")
    assert roulette.kind_title("crystal") == "Кристальная"
    assert roulette.is_kind("classic") is True
    assert roulette.is_kind("nope") is False


def test_segment_index_for_crystal_keys():
    for key in roulette.CRYSTAL_WEIGHTS:
        index = roulette.crystal_segment_index(key)
        assert roulette.crystal_segments()[index]["key"] == key


def test_count_is_clamped_to_three():
    assert roulette.clamp_count(0) == 1
    assert roulette.clamp_count(2) == 2
    assert roulette.clamp_count(99) == roulette.MAX_SPINS_AT_ONCE
    assert roulette.clamp_count("junk") == 1


def test_spin_plan_uses_free_spins_first():
    price = roulette.CRYSTAL_SPIN_PRICE
    assert roulette.spin_plan(1, 1, price) == (0, 0)
    assert roulette.spin_plan(1, 3, price) == (2, 2 * price)
    assert roulette.spin_plan(0, 2, price) == (2, 2 * price)
    assert roulette.spin_plan(3, 3, price) == (0, 0)


def test_crystal_spin_price_and_free_limit():
    assert roulette.CRYSTAL_SPIN_PRICE == 25_000
    assert roulette.CRYSTAL_SPINS_PER_DAY == 1


def test_prefs_clean_returns_defaults_for_junk():
    from app.webapp import PREFS_DEFAULTS, _prefs_clean

    cleaned = _prefs_clean(None)
    assert cleaned == PREFS_DEFAULTS
    cleaned = _prefs_clean({"fx": False, "view_classic": "reel", "hacker": 1})
    assert cleaned["fx"] is False
    assert cleaned["view_classic"] == "reel"
    assert "hacker" not in cleaned


def test_prefs_clean_rejects_unknown_view_and_card():
    from app.webapp import _prefs_clean

    cleaned = _prefs_clean({"view_crystal": "spiral", "pinned": "not_a_card"})
    assert cleaned["view_crystal"] == "wheel"
    assert cleaned["pinned"] == ""
