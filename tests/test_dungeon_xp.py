"""Полоса опыта и починка прокачки уровней."""

from app.webapp import DUNGEON_PAGE


def test_xp_bar_in_hud():
    assert 'id="xpfill"' in DUNGEON_PAGE
    assert 'id="xptxt"' in DUNGEON_PAGE
    assert "function xpPaint(" in DUNGEON_PAGE
    # обновляется вместе с остальным HUD и после начисления опыта
    assert "xpPaint();" in DUNGEON_PAGE
    # подсказка, сколько ещё мобов
    assert "мобов" in DUNGEON_PAGE


def test_one_hp_formula():
    assert "function heroMax(" in DUNGEON_PAGE
    assert "P.max = heroMax(level);" in DUNGEON_PAGE
    assert "P.max = heroMax(stats.lvl);" in DUNGEON_PAGE
    assert "P.max = 120 + (level - 1) * 8" not in DUNGEON_PAGE


def test_leveling_is_reachable():
    # кривая опыта и мягкий гейт по локациям
    assert "Math.round(60 * Math.pow(Math.max(1, lvl), 1.5))" in DUNGEON_PAGE
    assert "function zoneReq(y){ return 1 + zoneIndex(y) * 5; }" in DUNGEON_PAGE
    # старый гейт 25 уровней за локацию — та самая причина «опыт не капал»
    assert "zoneIndex(y) * 25" not in DUNGEON_PAGE


def test_weak_kills_still_give_xp():
    assert "gainExp(Math.round(baseXp * 0.3))" in DUNGEON_PAGE
    assert "опыта нет" not in DUNGEON_PAGE


def test_stored_exp_levels_up_on_load():
    # если в базе накопился опыт сверх нового порога — уровень догоняется
    assert "while (stats.exp >= expNeed(stats.lvl) && stats.lvl < 999)" in DUNGEON_PAGE
