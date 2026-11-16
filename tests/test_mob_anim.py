"""Мобы на арене: анимация удара и расталкивание."""

from app.webapp import DUNGEON_PAGE


def _mob_block() -> str:
    start = DUNGEON_PAGE.index("ARENA.mobs = ARENA.mobs.filter")
    return DUNGEON_PAGE[start:start + 1400]


def test_mob_attack_animation():
    block = _mob_block()
    assert "m.atk = 0.35;" in block
    assert 'arenaBossSheet(ARENA.zi, m.atk > 0 ? "atk" : "idle")' in DUNGEON_PAGE


def test_mobs_push_apart():
    block = _mob_block()
    assert "if (od < 24)" in block
    assert "m.x -= ox / od * push;" in block


def test_mob_hit_respects_dash_guard():
    block = _mob_block()
    assert "!dashGuard" in block
