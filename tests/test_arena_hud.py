"""Индикаторы фазы и подмоги на арене босса."""

from app.webapp import DUNGEON_PAGE


def test_phase_and_minion_indicators():
    assert '"ФАЗА " + b.phase + "/3"' in DUNGEON_PAGE
    assert '"ПОДМОГА " + ARENA.mobs.length' in DUNGEON_PAGE
    assert '"ЗАЛП " + ARENA.volley' in DUNGEON_PAGE
