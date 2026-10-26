"""Кейс «Ультра»: шансы, цена, выдача наград."""

import random

from app import cards, cases
from app.games_page import CASE_PAGE


def test_price_and_odds():
    assert cases.ULTRA_CASE_PRICE == 15_000
    assert set(cases.ULTRA_CASE_IDS) == {"daniyar_epic", "valeriya"}
    total = sum(cases.ULTRA_CASE_WEIGHTS.values())
    assert abs(total - 1.0) < 1e-9
    # по ТЗ: ульта 0.01%, крутка 1%, очки 1%, остальное пусто
    assert cases.ULTRA_CASE_WEIGHTS["ultra"] == 0.0001
    assert cases.ULTRA_CASE_WEIGHTS["spin"] == 0.01
    assert cases.ULTRA_CASE_WEIGHTS["points"] == 0.01
    assert cases.ULTRA_CASE_WEIGHTS["empty"] == 0.9799
    odds = {item["key"]: item["chance"] for item in cases.ultra_case_odds()}
    assert odds == {"ultra": 0.01, "spin": 1.0, "points": 1.0, "empty": 97.99}


def test_cards_exist_and_are_ultra():
    for card_id in cases.ULTRA_CASE_IDS:
        card = cards.CARDS_BY_ID[card_id]
        assert card.rarity == "ultra", card_id
        assert card.name


def test_points_reward_is_up_to_50k():
    rng = random.Random(7)
    for _ in range(500):
        result = cases.roll_ultra_case(rng)
        if result["kind"] == "points":
            assert cases.ULTRA_POINTS_MIN <= result["amount"] <= 50_000
        if result["kind"] == "ultra":
            assert result["card"] in cases.ULTRA_CASE_IDS


def test_distribution_is_close_to_rules():
    rng = random.Random(11)
    rolls = [cases.roll_ultra_case(rng)["kind"] for _ in range(200_000)]
    empty = rolls.count("empty") / len(rolls)
    spin = rolls.count("spin") / len(rolls)
    assert abs(empty - 0.9799) < 0.005
    assert abs(spin - 0.01) < 0.002


def test_page_has_ultra_block():
    for marker in ('id="ultraOpen"', 'id="ultraOdds"', 'id="ultraPrice"',
                   "/api/case/ultra", "ultraOpen()"):
        assert marker in CASE_PAGE, marker
