"""Оружейные кейсы подземелья: каталог, ролл и выдача в сумку героя."""

import random

from app import dungeon_case, shop


def test_cases_are_in_catalog():
    skus = [entry.sku for entry in shop.catalog()]
    for case in dungeon_case.CASES:
        assert case["sku"] in skus
        entry = shop.find(case["sku"])
        assert entry.kind == "weapon_case"
        assert entry.price == case["price"]


def test_roll_matches_dungeon_weapon_stats():
    # id и статы должны совпадать с тем, что рисует страница подземелья
    stats = dungeon_case.stats("sword_7_4")
    assert stats["name"] == "Пламенный Ятаган"
    assert stats["dmg"] == 216
    assert stats["range"] == 103


def test_cases_respect_level_cap():
    weapon = dungeon_case.roll(level=1, bonus=0, rng=random.Random(1))
    assert weapon["tier"] <= 0
    top = dungeon_case.roll(level=400, bonus=2, rng=random.Random(2))
    assert top["tier"] <= 9


def test_roll_never_gives_junk_low_tiers():
    # внутри кейса тир не ниже двух от потолка
    for level in (24, 60, 120, 300):
        cap = dungeon_case.tier_cap(level)
        for seed in range(20):
            weapon = dungeon_case.roll(level, 0, random.Random(seed))
            assert weapon["tier"] >= max(0, cap - 2)


def test_unknown_weapon_is_rejected():
    assert dungeon_case.stats("nonsense") is None
    assert dungeon_case.stats("sword_9_9") is None
