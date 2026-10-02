from collections import Counter

from app.cards import CARDS, CARDS_BY_ID, CARDS_BY_RARITY, RARITIES, cards_sorted_for_user

EXPECTED = {
    "rare": 4,
    "superrare": 4,
    "epic": 10,
    "mythic": 8,
    "legendary": 3,
    "secret": 2,
    "ultra": 1,
}


def test_total_and_unique_ids():
    assert len(CARDS) == 32
    assert len(CARDS_BY_ID) == 32


def test_duplicate_names_have_distinct_ids():
    names = Counter(card.name for card in CARDS)
    assert names["Амир"] == 2
    assert names["Данияр"] == 2
    assert names["Тамерлан"] == 2
    assert all(card_id for card_id in CARDS_BY_ID)


def test_rarity_counts_match_spec():
    for rarity, expected in EXPECTED.items():
        assert len(CARDS_BY_RARITY[rarity]) == expected, rarity
    assert sum(EXPECTED.values()) == 32


def test_weights_sum_to_one():
    assert abs(sum(r.weight for r in RARITIES.values()) - 1.0) < 1e-9


def test_balance_is_tight():
    budgets = [card.budget for card in CARDS]
    assert max(budgets) - min(budgets) <= 65, budgets
    assert all(card.hp >= 80 for card in CARDS)
    assert all(card.atk >= 8 for card in CARDS)


def test_points_match_spec():
    assert CARDS_BY_ID["valeriya"].points == 15000
    assert CARDS_BY_ID["oleg"].points == 250
    assert CARDS_BY_ID["amir_1"].points == CARDS_BY_ID["amir_2"].points == 5000


def test_sorting_prefers_rarity():
    order = [c.card_id for c in cards_sorted_for_user(["oleg", "valeriya", "amir_1", "daniel"])]
    assert order[0] == "valeriya"
    assert order[-1] == "oleg"
