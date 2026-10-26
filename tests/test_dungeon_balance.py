"""Ребаланс: редкость оружия, дроп 5%, античит PvP."""

from app import dungeon, db
from app.webapp import DUNGEON_PAGE, QUESTS_PAGE


def test_tier_tables_are_sane():
    assert len(dungeon.MOB_TIER_WEIGHTS) == 10
    assert len(dungeon.BOSS_TIER_WEIGHTS) == 10
    # у мобов почти всё — низкие тиры
    assert dungeon.MOB_TIER_WEIGHTS[0] > dungeon.MOB_TIER_WEIGHTS[5]
    # у боссов высокие тиры идут чаще низких
    assert dungeon.BOSS_TIER_WEIGHTS[6] > dungeon.BOSS_TIER_WEIGHTS[3]
    # топ-тир есть, но он исчезающе редкий (0.01%)
    total = sum(dungeon.BOSS_TIER_WEIGHTS)
    assert dungeon.BOSS_TIER_WEIGHTS[9] / total * 100 < 0.02
    mob_total = sum(dungeon.MOB_TIER_WEIGHTS)
    assert dungeon.MOB_TIER_WEIGHTS[9] / mob_total * 100 < 0.02


def test_mob_drop_is_five_percent():
    assert dungeon.MOB_DROP_CHANCE == 0.05
    assert DUNGEON_PAGE.count("MOB_DROP_CHANCE = 0.05") == 1
    assert "Math.random() < 0.22" not in DUNGEON_PAGE


def test_boss_weapon_is_deterministic_and_valid():
    first = dungeon.boss_weapon(777)
    assert first == dungeon.boss_weapon(777)
    assert first.split("_")[0] in dungeon.WEAPON_KINDS
    assert 0 <= int(first.split("_")[1]) <= 9
    assert 0 <= int(first.split("_")[2]) <= 4
    # разные seed дают разные стволы (разнообразие есть, но верхние тиры редки)
    assert len({dungeon.boss_weapon(seed) for seed in range(200)}) > 50


def test_boss_tiers_are_high_mostly():
    tiers = [int(dungeon.boss_weapon(seed).split("_")[1]) for seed in range(400)]
    assert min(tiers) >= 2
    assert sum(1 for tier in tiers if tier >= 5) > len(tiers) * 0.5


def test_pvp_threshold_and_ban():
    assert db.PVP_PAIR_LIMIT == 5
    assert db.PVP_BAN_DAYS == 7
    assert "if fights > PVP_PAIR_LIMIT:" in open("app/db.py", encoding="utf-8").read()
    assert "pvp_ban_until" in open("app/db.py", encoding="utf-8").read()
    assert "pvp_ban_until" in open("schema.sql", encoding="utf-8").read()


def test_pvp_ban_blocks_battle():
    source = open("app/handlers.py", encoding="utf-8").read()
    assert "pvp_ban_until" in source
    assert "PvP закрыт до" in source


def test_quests_page_mentions_new_rules():
    assert "Больше 5 боёв" in QUESTS_PAGE
    assert "бан PvP на неделю" in QUESTS_PAGE


def test_client_rolls_boss_loot():
    assert "function rollWeapon(" in DUNGEON_PAGE
    assert "BOSS_TIER_WEIGHTS" in DUNGEON_PAGE
    assert "room.reward.weapon" in DUNGEON_PAGE
