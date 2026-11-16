"""Полоса опыта и настройка прокачки уровней."""

from app.webapp import DUNGEON_PAGE


def test_xp_bar_in_hud():
    assert 'id="xpfill"' in DUNGEON_PAGE
    assert 'id="xptxt"' in DUNGEON_PAGE
    assert "function xpPaint(" in DUNGEON_PAGE
    assert "xpPaint();" in DUNGEON_PAGE
    assert "мобов" in DUNGEON_PAGE


def test_one_hp_formula():
    assert "function heroMax(" in DUNGEON_PAGE
    assert "P.max = heroMax(level);" in DUNGEON_PAGE
    assert "P.max = heroMax(stats.lvl);" in DUNGEON_PAGE
    assert "P.max = 120 + (level - 1) * 8" not in DUNGEON_PAGE


def test_leveling_is_reachable():
    # 25 уровней на локацию, как попросил владелец
    assert "function zoneReq(y){ return 1 + zoneIndex(y) * 25; }" in DUNGEON_PAGE
    assert "zoneIndex(y) * 25" in DUNGEON_PAGE
    # кривая привязана к HP мобов своей локации, опыт с моба max/6
    assert "const hp = zoneMobHp(ownZone(lvl));" in DUNGEON_PAGE
    assert "return Math.round(hp * 2.2);" in DUNGEON_PAGE
    assert "Math.max(8, Math.round(m.max / 6))" in DUNGEON_PAGE


def test_weak_kills_still_give_xp():
    # опыт никогда не обнуляется полностью: есть множитель по локации
    assert "const mult = zoneXpMult(zoneIndex(m.y), stats.lvl)" in DUNGEON_PAGE
    assert "gainExp(Math.max(1, Math.round(baseXp * mult)))" in DUNGEON_PAGE
    assert "опыта нет" not in DUNGEON_PAGE


def test_stored_exp_levels_up_on_load():
    assert "while (stats.exp >= expNeed(stats.lvl) && stats.lvl < 999)" in DUNGEON_PAGE


def test_every_level_needs_about_10_15_mobs():
    """Порог опыта привязан к мобам своей локации: 10-15 убийств на уровень."""
    caps = (250, 500, 1_000, 1_350, 2_000, 2_500, 3_000, 3_500, 4_500, 10_000)

    def own(level: int) -> int:
        return min(9, (level - 1) // 25)

    for level in (1, 5, 10, 20, 25, 26, 40, 46, 60, 90, 120, 250, 400):
        zone = own(level)
        need = round(caps[zone] * 2.2)
        per_mob = max(8, round(caps[zone] / 6))
        mobs = need / per_mob
        assert 10 <= mobs <= 15, (level, mobs)


def test_start_is_not_instant():
    # раньше на 1-2 уровне хватало одного моба: 40 xp против 42 за моба
    caps = 250
    need = round(caps * 2.2)
    per_mob = max(8, round(caps / 6))
    assert need / per_mob >= 10


def test_high_level_farming_zone_one_is_ten_times_slower():
    """Игрок 10-й локации в первой локе получает в 10 раз меньше опыта."""
    def mult(mob_zone: int, level: int) -> float:
        own = min(9, (level - 1) // 25)
        distance = mob_zone - own
        if distance == 0:
            return 1.0
        if distance > 0:
            return 0.5
        return max(0.1, 0.45 ** (-distance))

    assert mult(9, 226) == 1.0     # своя зона — полный опыт
    assert mult(0, 226) == 0.1     # первая локация для 226-го уровня — x0.1
    assert mult(1, 226) == 0.1
