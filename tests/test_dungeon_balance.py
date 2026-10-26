"""Дроп оружия, античит PvP и текст правил на странице заданий."""

from app import db, dungeon
from app.webapp import DUNGEON_PAGE, QUESTS_PAGE


def test_mob_drop_is_five_percent():
    assert dungeon.MOB_DROP_CHANCE == 0.05
    assert DUNGEON_PAGE.count("MOB_DROP_CHANCE = 0.05") == 1
    assert "Math.random() < 0.22" not in DUNGEON_PAGE


def test_boss_weapon_is_deterministic_and_valid():
    first = dungeon.boss_weapon(777, 3)
    assert first == dungeon.boss_weapon(777, 3)
    kind, rank, variant = first.split("_")
    assert kind in dungeon.WEAPON_KINDS
    assert 0 <= int(rank) <= 9
    assert 0 <= int(variant) <= 4
    # разные seed дают разные стволы (в одной зоне выбор узкий — смотрим все)
    variety = {dungeon.boss_weapon(seed, zone) for zone in range(10) for seed in range(50)}
    assert len(variety) > 60


def test_pvp_threshold_and_ban():
    assert db.PVP_PAIR_LIMIT == 5
    assert db.PVP_BAN_DAYS == 7
    source = open("app/db.py", encoding="utf-8").read()
    assert "if fights > PVP_PAIR_LIMIT:" in source
    assert "pvp_ban_until" in source
    assert "pvp_ban_until" in open("schema.sql", encoding="utf-8").read()


def test_pvp_ban_blocks_battle():
    source = open("app/handlers.py", encoding="utf-8").read()
    assert "pvp_ban_until" in source
    assert "PvP закрыт до" in source


def test_quests_page_mentions_new_rules():
    assert "Больше 5 боёв" in QUESTS_PAGE
    assert "бан PvP на неделю" in QUESTS_PAGE


def test_client_rolls_boss_loot():
    assert "function rollWeapon(zi, fromBoss)" in DUNGEON_PAGE
    assert "room.reward.weapon" in DUNGEON_PAGE
