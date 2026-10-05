"""Рулетка и кейсы: сброс, веса, содержимое."""

import random
from datetime import datetime, timezone

from app.cards import CARDS_BY_RARITY, get_card
from app.cases import CASE_PRICE, CASE_RARITY_WEIGHTS, roll_case_card, roll_case_rarity
from app.market import parse_handle
from app.roulette import (
    MAIN_CARD_ID,
    POINT_TIERS,
    PRIZE_CARD,
    PRIZE_CASE,
    PRIZE_POINTS,
    PRIZE_WEIGHTS,
    ROULETTE_RESET_HOUR_UTC,
    next_roulette_reset,
    roll_points,
    roll_prize,
    roulette_day_key,
)


def test_reset_is_at_2000_ekb():
    assert ROULETTE_RESET_HOUR_UTC == 15  # 20:00 UTC+5


def test_day_key_flips_at_1500_utc():
    before = datetime(2026, 6, 1, 14, 59, tzinfo=timezone.utc)
    after = datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc)
    assert roulette_day_key(before) != roulette_day_key(after)
    assert roulette_day_key(after) == datetime(2026, 6, 1).date()


def test_next_reset_is_in_the_future():
    moment = datetime(2026, 6, 1, 16, 0, tzinfo=timezone.utc)
    assert next_roulette_reset(moment) == datetime(2026, 6, 2, 15, tzinfo=timezone.utc)
    assert next_roulette_reset(datetime(2026, 6, 1, 3, 0, tzinfo=timezone.utc)) == datetime(
        2026, 6, 1, 15, tzinfo=timezone.utc
    )


def test_prize_weights_sum_to_one():
    assert abs(sum(PRIZE_WEIGHTS.values()) - 1.0) < 1e-9


def test_cases_are_rare_and_the_main_prize_is_rarer():
    assert PRIZE_WEIGHTS[PRIZE_CASE] < PRIZE_WEIGHTS[PRIZE_POINTS]
    assert PRIZE_WEIGHTS[PRIZE_CARD] < PRIZE_WEIGHTS[PRIZE_CASE]


def test_prize_distribution_matches_weights():
    rng = random.Random(99)
    counts = {PRIZE_POINTS: 0, PRIZE_CASE: 0, PRIZE_CARD: 0}
    for _ in range(200_000):
        counts[roll_prize(rng)[0]] += 1
    total = sum(counts.values())
    for kind, weight in PRIZE_WEIGHTS.items():
        assert abs(counts[kind] / total - weight) < 0.005, kind


def test_main_prize_is_daniel_only():
    rng = random.Random(5)
    cards = set()
    for _ in range(50_000):
        kind, value = roll_prize(rng)
        if kind == PRIZE_CARD:
            cards.add(value)
    assert cards, "главный приз должен иногда выпадать"
    assert cards <= {MAIN_CARD_ID}


def test_points_land_inside_tiers():
    rng = random.Random(3)
    low = min(t[0] for t in POINT_TIERS)
    high = max(t[1] for t in POINT_TIERS)
    for _ in range(5000):
        value = roll_points(rng)
        assert low <= value <= high


def test_case_never_drops_below_epic():
    rng = random.Random(11)
    for _ in range(30_000):
        card = roll_case_card(rng)
        assert card.rarity in CASE_RARITY_WEIGHTS, card.rarity
        assert card.rarity not in {"rare", "superrare"}


def test_case_can_drop_every_high_rarity():
    rng = random.Random(2026)
    seen = {roll_case_rarity(rng) for _ in range(200_000)}
    assert seen == set(CASE_RARITY_WEIGHTS)


def test_case_rarity_weights_sum_to_one():
    assert abs(sum(CASE_RARITY_WEIGHTS.values()) - 1.0) < 1e-9


def test_case_price_is_5000():
    assert CASE_PRICE == 5000


def test_case_handle_parsing():
    assert parse_handle("#c3") == ("case", 3)
    assert parse_handle("c12") == ("case", 12)
    assert parse_handle("#C7") == ("case", 7)
    # обычные слаги не должны ломаться
    assert parse_handle("#oleg") == ("card", "oleg")
    assert parse_handle("#12") == ("inventory", 12)


def test_every_high_rarity_has_cards():
    for rarity in CASE_RARITY_WEIGHTS:
        assert len(CARDS_BY_RARITY[rarity]) > 0
    assert get_card("valeriya").rarity == "ultra"
