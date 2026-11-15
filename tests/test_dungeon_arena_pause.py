"""Арена останавливает мир подземелья."""

from app.webapp import DUNGEON_PAGE


def test_world_pauses_during_arena():
    # цикл мира выходит, пока идёт бой, иначе круг босса перезапускает арену
    assert "if (ARENA.on){ requestAnimationFrame(loop); return; }" in DUNGEON_PAGE
    assert "if (ARENA.on) return;" in DUNGEON_PAGE


def test_arena_spawn_is_not_in_wall():
    assert "while (arenaBlocked(ARENA.hero.x, ARENA.hero.y, 18)" in DUNGEON_PAGE
