from collections import Counter

from app.cards import (
    CARDS,
    CARDS_BY_ID,
    CARDS_BY_RARITY,
    RARITIES,
    cards_sorted_for_user,
    get_card,
)

EXPECTED = {
    "rare": 4,
    "superrare": 4,
    "epic": 10,
    "mythic": 9,
    "legendary": 4,
    "secret": 5,
    "ultra": 1,
    "teacher": 13,
}


def test_total_and_unique_ids():
    assert len(CARDS) == 50
    assert len(CARDS_BY_ID) == 50


def test_duplicate_names_have_distinct_ids():
    names = Counter(card.name for card in CARDS)
    assert names["Амир"] == 2
    assert names["Данияр"] == 2
    assert names["Тамерлан"] == 2
    assert all(card_id for card_id in CARDS_BY_ID)


def test_rarity_counts_match_spec():
    for rarity, expected in EXPECTED.items():
        assert len(CARDS_BY_RARITY[rarity]) == expected, rarity
    assert sum(EXPECTED.values()) == 50


def test_weights_sum_to_one():
    assert abs(sum(r.weight for r in RARITIES.values()) - 1.0) < 1e-9


def test_students_balance_is_tight():
    budgets = [card.budget for card in CARDS if card.rarity != "teacher"]
    assert max(budgets) - min(budgets) <= 400, budgets
    assert all(card.hp >= 500 for card in CARDS)
    assert all(card.atk >= 16 for card in CARDS)


def test_teacher_abilities_show_concrete_effects():
    from app.render import describe_ability

    teachers = [card for card in CARDS if card.rarity == "teacher"]
    for card in teachers:
        assert describe_ability(card), f"{card.card_id}: у способности нет эффектов"


def test_glafira_and_mikhail_are_a_pair():
    from app.cards import CARD_PAIRS

    assert CARD_PAIRS.get("glafira") == "mikhail_nik"
    assert CARD_PAIRS.get("mikhail_nik") == "glafira"
    assert get_card("glafira").description
    assert get_card("mikhail_nik").description


def test_teachers_are_stronger_and_varied():
    teachers = [card for card in CARDS if card.rarity == "teacher"]
    budgets = [card.budget for card in teachers]
    assert min(budgets) >= 1100, budgets
    assert max(budgets) <= 1600, budgets
    assert all(card.description for card in teachers), "у учителя должно быть описание"
    assert len({card.ability.name for card in teachers}) == len(teachers), (
        "у каждого учителя своя способность"
    )


def test_points_match_spec():
    assert CARDS_BY_ID["valeriya"].points == 15000
    assert CARDS_BY_ID["oleg"].points == 250
    assert CARDS_BY_ID["amir_1"].points == CARDS_BY_ID["amir_2"].points == 5000


def test_sorting_prefers_rarity():
    order = [c.card_id for c in cards_sorted_for_user(["oleg", "valeriya", "amir_1", "daniel"])]
    assert order[0] == "valeriya"
    assert order[-1] == "oleg"

def test_duplicate_names_are_split_by_surname():
    from collections import Counter

    display = Counter(card.display_name for card in CARDS)
    assert all(count == 1 for count in display.values()), "отображаемые имена не должны повторяться"
    assert len(display) == 50


def test_only_duplicate_names_have_surnames():
    names = Counter(card.name for card in CARDS)
    for card in CARDS:
        if names[card.name] > 1:
            assert card.surname, f"{card.card_id} должен иметь фамилию"
        else:
            assert card.surname is None, f"{card.card_id} не должен иметь фамилию"


def test_expected_surnames():
    assert get_card("tamerlan_mif").display_name == "Тамерлан Гиндуллин"
    assert get_card("tamerlan_epic").display_name == "Тамерлан Хазиатметов"
    assert get_card("amir_1").display_name == "Амир Насибуллин"
    assert get_card("amir_2").display_name == "Амир Нугуманов"
    assert get_card("daniyar_mif").display_name == "Данияр Жайлибаев"
    assert get_card("daniyar_epic").display_name == "Данияр Садыков"
