"""Бой в подземелье ближе к ритму боя с эльфами."""

import re

from app.webapp import DUNGEON_PAGE


def _snip(pattern: str) -> str:
    m = re.search(pattern, DUNGEON_PAGE)
    assert m, pattern
    return m.group(0)


def test_hero_runs_faster():
    assert "const speed = 255;" in DUNGEON_PAGE


def test_attacks_and_dash_are_quicker():
    assert '0.56 * w.spd : 0.36 * w.spd' in DUNGEON_PAGE
    assert "P.dashCd = 1.6;" in DUNGEON_PAGE


def test_mobs_are_denser_and_faster():
    assert "spawnMobs(24);" in DUNGEON_PAGE
    assert "mobs.length < 14" in DUNGEON_PAGE
    assert "sp: Math.round(type.sp * 1.2)" in DUNGEON_PAGE


def test_arena_accepts_keyboard():
    # на ПК WASD не работал в бою с боссом: арена слушала только джойстик
    assert "function arenaInput()" in DUNGEON_PAGE
    start = DUNGEON_PAGE.index("function arenaInput()")
    body = DUNGEON_PAGE[start:start + 500]
    assert 'keys["w"]' in body and 'keys["d"]' in body
    assert "const IN = arenaInput();" in DUNGEON_PAGE
    assert "ARENA.joy.dx * sp * dt" not in DUNGEON_PAGE
