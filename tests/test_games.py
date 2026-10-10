"""Мини-аппки: пул кейсов и сегменты колеса рулетки."""

from app import cases, roulette


def test_case_pool_has_colors_and_only_case_rarities():
    pool = cases.case_pool()
    assert pool, "пул кейса не должен быть пустым"
    for item in pool:
        assert item["color"].startswith("#")
        assert item["rarity"] in cases.CASE_RARITY_WEIGHTS
        assert item["emoji"] and item["name"]


def test_wheel_segments_weights_sum_to_one():
    segments = roulette.wheel_segments()
    assert len(segments) == len(roulette.POINT_TIERS) + 2
    total = sum(float(item["weight"]) for item in segments)
    assert abs(total - 1.0) < 1e-9, total


def test_segment_index_maps_every_prize():
    assert roulette.segment_index(("points", 100)) == 0
    assert roulette.segment_index(("points", 750)) == 1
    assert roulette.segment_index(("points", 1500)) == 2
    assert roulette.segment_index(("points", 3000)) == 3
    assert roulette.segment_index(("case", "case")) == 4
    assert roulette.segment_index(("card", "daniel")) == 5
