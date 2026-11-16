"""Плашка входа к боссу и нулевой опыт за слабого босса."""

from app.webapp import DUNGEON_PAGE


def test_warning_is_static_markup():
    assert '<div id="lvlwarn">' in DUNGEON_PAGE
    assert 'id="lwtext"' in DUNGEON_PAGE
    assert 'id="lvlno"' in DUNGEON_PAGE
    assert 'id="lvlyes"' in DUNGEON_PAGE
    assert "#lvlwarn.on{display:flex}" in DUNGEON_PAGE


def test_warning_buttons_are_bound_once():
    assert "function bindLevelWarn()" in DUNGEON_PAGE
    assert "bindLevelWarn();" in DUNGEON_PAGE


def test_accepting_sets_forced():
    block = DUNGEON_PAGE[DUNGEON_PAGE.index('yes.onclick'):][:400]
    assert "bs.forced = true;" in block
    assert "bs.t = 0;" in block


def test_underlevel_fight_gives_no_exp():
    assert "const under = stats.lvl < zoneReq(boss.y);" in DUNGEON_PAGE
    assert "exp: under ? 0 : 50 + zi * 40" in DUNGEON_PAGE
    assert "if (ARENA.reward.exp) stats.exp += ARENA.reward.exp;" in DUNGEON_PAGE
    assert "опыт: 0 (босс не по уровню)" in DUNGEON_PAGE
