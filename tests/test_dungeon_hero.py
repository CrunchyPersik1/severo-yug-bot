"""Прогресс героя подземелья: санитайзеры и разбор сумки."""

from app import dungeon_hero as hero


def test_defaults_for_empty_payload():
    data = hero.sanitize({})
    assert data == {"level": 1, "exp": 0, "coins": 0, "kills": 0,
                    "weapon": None, "bag": []}


def test_numbers_are_clamped():
    data = hero.sanitize({"level": 5000, "exp": -10, "coins": 10 ** 20,
                          "kills": -1})
    assert data["level"] == hero.MAX_LEVEL
    assert data["exp"] == 0
    assert data["coins"] == hero.MAX_COINS
    assert data["kills"] == 0
    assert hero.sanitize({"level": "abc"})["level"] == 1


def test_weapon_id_is_validated():
    assert hero.clean_weapon("sword_3_2") == "sword_3_2"
    assert hero.clean_weapon("bow_0_0") == "bow_0_0"
    assert hero.clean_weapon("ракета") is None
    assert hero.clean_weapon("sword_10_0") is None      # тиров ровно 10: 0..9
    assert hero.clean_weapon("sword_1_5") is None       # вариантов 5: 0..4
    assert hero.clean_weapon(None) is None


def test_bag_drops_junk_and_dupes():
    bag = hero.clean_bag(["sword_1_0", "sword_1_0", "мусор", None, "staff_2_4"])
    assert bag == ["sword_1_0", "staff_2_4"]


def test_bag_from_jsonb_string():
    # jsonb из asyncpg приходит строкой
    assert hero.clean_bag('["bow_1_1","bow_1_1"]') == ["bow_1_1"]
    assert hero.clean_bag("не json") == []
    assert hero.clean_bag(None) == []


def test_bag_is_limited():
    everything = [
        "%s_%d_%d" % (kind, tier, variant)
        for kind in ("sword", "bow", "staff")
        for tier in range(10)
        for variant in range(5)
    ]
    assert len(everything) == 150
    assert len(hero.clean_bag(everything)) == hero.MAX_BAG
    assert len(hero.clean_bag(everything * 3)) == hero.MAX_BAG


def test_weapon_is_inside_bag():
    data = hero.sanitize({"weapon": "bow_2_0", "bag": ["sword_1_0"]})
    assert data["bag"][0] == "bow_2_0"
    assert data["weapon"] == "bow_2_0"


def test_weapon_falls_back_to_bag_head():
    data = hero.sanitize({"weapon": "мусор", "bag": ["staff_0_1"]})
    assert data["weapon"] == "staff_0_1"


def test_payload_of_missing_row():
    assert hero.hero_payload(None) == hero.EMPTY
