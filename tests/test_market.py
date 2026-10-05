"""Логика рынка: цены, статы, репутация и разбор ссылок на карты."""

import random

from app.cards import CARDS, get_card
from app.items import AURAS, BACKGROUNDS, BY_SLOT, EFFECTS, Item, SLOTS, roll_item, roll_slot
from app.market import (
    CHEAP_RATIO,
    DEF_CAP,
    HONEST_RATIO,
    MARKET_FEE,
    RARITY_COEF,
    RATING_START,
    SUSPECT_RATIO,
    UPGRADE_PRICE,
    can_sell,
    card_handle,
    clamp_rating,
    effective_stats,
    inventory_handle,
    is_honest_deal,
    listing_penalty,
    market_fee,
    market_price,
    parse_handle,
    price_ratio,
    seller_income,
    sum_bonus,
)


def test_there_are_ten_items_in_each_category():
    assert len(AURAS) == 10
    assert len(BACKGROUNDS) == 10
    assert len(EFFECTS) == 10
    assert set(BY_SLOT) == set(SLOTS)


def test_all_item_names_are_unique():
    names = [item.name for item in AURAS + BACKGROUNDS + EFFECTS]
    assert len(names) == len(set(names)) == 30


def test_aura_touches_several_stats_others_only_one():
    for aura in AURAS:
        assert len(aura.bonus) >= 2, aura.name
    for item in BACKGROUNDS + EFFECTS:
        assert len(item.bonus) == 1, item.name


def test_items_have_both_positive_and_negative_bonuses():
    values = [v for item in AURAS + BACKGROUNDS + EFFECTS for v in item.bonus.values()]
    assert max(values) > 0
    assert min(values) < 0


def test_roll_is_uniform_within_category():
    rng = random.Random(7)
    counts = {item.id: 0 for item in AURAS}
    for _ in range(60_000):
        counts[roll_item("aura", rng).id] += 1
    for value in counts.values():
        assert abs(value / 60_000 - 0.1) < 0.01


def test_roll_slot_picks_only_free_slots():
    rng = random.Random(1)
    filled = {"aura": Item(1, "x", {"atk": 1})}
    picks = {roll_slot(filled, rng) for _ in range(500)}
    assert picks <= {"background", "effect"}
    assert roll_slot({slot: object() for slot in SLOTS}, rng) is None


def test_effective_stats_apply_percentages():
    card = get_card("oleg")  # atk 10, hp 95
    assert effective_stats(card, {}) == {"atk": 10, "hp": 95, "def": 0}
    buffed = effective_stats(card, {"atk": 50, "hp": 20, "def": 15})
    assert buffed["atk"] == 15
    assert buffed["hp"] == 114
    assert buffed["def"] == 15


def test_defense_is_capped_and_never_negative():
    card = get_card("oleg")
    assert effective_stats(card, {"def": 500})["def"] == DEF_CAP
    assert effective_stats(card, {"def": -50})["def"] == 0


def test_effective_stats_never_drop_below_one():
    card = get_card("oleg")
    stats = effective_stats(card, {"atk": -100, "hp": -100})
    assert stats["atk"] >= 1 and stats["hp"] >= 1


def test_market_price_grows_with_rarity_and_upgrades():
    rare = get_card("oleg")        # 250, редкий
    ultra = get_card("valeriya")   # 15000, ультра
    assert market_price(rare) == 250
    assert market_price(ultra) == 60000
    # 50 + 15 = 65 процентных пунктов → множитель 1 + 65*2/100 = 2.3
    assert market_price(rare, {"atk": 50, "def": 15}) == round(250 * 2.3)


def test_upgrade_price_is_worth_several_times_base():
    """Топовый набор улучшений поднимает цену минимум вдвое от базы."""
    # Вечный Полдень (+12/+12/+12) + Кровавая Луна (+20 атака) + Пламя Души (+25 атака)
    best = sum_bonus(AURAS[8].bonus, BACKGROUNDS[4].bonus, EFFECTS[2].bonus)
    for card in CARDS:
        ratio = market_price(card, best) / card.points
        # редкость даёт 1..4x, улучшения сверху ещё ~2.3x
        expected_min = RARITY_COEF[card.rarity] * 2.0
        assert ratio >= expected_min, (card.card_id, ratio, expected_min)
        assert ratio <= 12, (card.card_id, ratio)


def test_upgrade_costs_750():
    assert UPGRADE_PRICE == 750


def test_fee_is_five_percent():
    assert market_fee(1000) == 50
    assert seller_income(1000) == 950
    assert MARKET_FEE == 0.05


def test_listing_penalties():
    assert listing_penalty(0.10) == (-1.0, True)
    assert listing_penalty(0.35) == (-0.5, False)
    assert listing_penalty(0.70) == (0.0, False)
    assert SUSPECT_RATIO == 0.20 and CHEAP_RATIO == 0.50


def test_honest_deal_threshold():
    assert is_honest_deal(800, 1000) is True
    assert is_honest_deal(799, 1000) is False
    assert HONEST_RATIO == 0.80


def test_rating_limits():
    assert RATING_START == 5.0
    assert can_sell(1.5) is True
    assert can_sell(1.49) is False
    assert clamp_rating(12) == 10.0
    assert clamp_rating(-3) == 0.0


def test_price_ratio_handles_zero_reference():
    assert price_ratio(100, 0) == 1.0


def test_handles_parse_correctly():
    assert parse_handle("#12") == ("inventory", 12)
    assert parse_handle("12") == ("inventory", 12)
    assert parse_handle("#oleg") == ("card", "oleg")
    assert parse_handle("amir_1") == ("card", "amir_1")
    assert parse_handle("  #Валерия ") == ("card", "валерия")
    assert parse_handle("") is None
    assert card_handle("oleg") == "#oleg"
    assert inventory_handle(7) == "#7"


def test_rarity_coefficients_cover_every_card():
    for card in CARDS:
        assert card.rarity in RARITY_COEF, card.card_id
