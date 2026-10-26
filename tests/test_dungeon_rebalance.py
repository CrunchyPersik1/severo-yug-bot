"""Ребаланс подземелья: HP мобов, капы урона, опыт."""

from app import dungeon
from app.webapp import DUNGEON_PAGE


def test_zone_tables_match_the_spec():
    # HP мобов по ТЗ: 250, 500, 1000, 1350, 2000, 2500, 3000, 3500, 4500, 10000
    assert dungeon.ZONE_MOB_HP == (250, 500, 1_000, 1_350, 2_000,
                                   2_500, 3_000, 3_500, 4_500, 10_000)
    # кап урона: 40 на первой, 400 на последней
    assert dungeon.ZONE_DMG_CAP[0] == 40
    assert dungeon.ZONE_DMG_CAP[-1] == 400
    assert list(dungeon.ZONE_DMG_CAP) == sorted(dungeon.ZONE_DMG_CAP)


def test_boss_hp_grows_over_five_thousand():
    hp = [dungeon.base_hp(zone) for zone in range(10)]
    assert hp == sorted(hp)
    assert hp[0] == 600
    assert hp[5] > 5_000      # с шестой локации боссы толще пяти тысяч
    assert dungeon.base_hp(9, 2) > dungeon.base_hp(9, 1)


def test_weapon_damage_and_rank_curve():
    assert dungeon.weapon_dmg(0, 0) == 10
    assert dungeon.weapon_dmg(9, 4) == 400
    # урон растёт и по рангу, и по варианту
    assert dungeon.weapon_dmg(6, 0) > dungeon.weapon_dmg(4, 4)
    assert dungeon.weapon_dmg(3, 2) > dungeon.weapon_dmg(3, 1)


def test_boss_weapon_fits_zone_cap():
    for zone in range(10):
        cap = dungeon.zone_cap(zone)
        for seed in range(40):
            weapon_id = dungeon.boss_weapon(seed, zone)
            parts = weapon_id.split("_")
            assert parts[0] in dungeon.WEAPON_KINDS
            dmg = dungeon.weapon_dmg(int(parts[1]), int(parts[2]))
            assert dmg <= cap, (zone, weapon_id, dmg, cap)
            # с босса не мусор: не ниже 80% капа
            assert dmg >= cap * 0.8, (zone, weapon_id, dmg, cap)


def test_first_zone_never_drops_imba():
    # первый босс не может выдать ствол сильнее 40
    for seed in range(200):
        weapon_id = dungeon.boss_weapon(seed, 0)
        _, rank, variant = weapon_id.split("_")
        assert dungeon.weapon_dmg(int(rank), int(variant)) <= 40


def test_page_uses_zone_tables():
    for marker in ("const ZONE_DMG_CAP", "const ZONE_MOB_HP",
                   "function zoneCap(", "function zoneMobHp(",
                   "function expNeed(", "function gainExp(",
                   "function rollWeapon(zi, fromBoss)"):
        assert marker in DUNGEON_PAGE, marker
    # старые веса по тирам убраны
    assert "MOB_TIER_WEIGHTS" not in DUNGEON_PAGE
    assert "BOSS_TIER_WEIGHTS" not in DUNGEON_PAGE
    # дроп мобов — только то, что влезает в кап локации
    assert "w.dmg <= cap && w.dmg >= floor" in DUNGEON_PAGE
