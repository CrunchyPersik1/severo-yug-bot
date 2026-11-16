"""Босс активный и крупный: темп атак, рыскание, размеры."""

from app.webapp import DUNGEON_PAGE


def test_boss_moves_faster():
    assert "sp: 120 + zi * 10" in DUNGEON_PAGE


def test_phase_three_triggers_volley_immediately():
    assert "b.cd = phase === 3 ? 0 : 400;" in DUNGEON_PAGE
    assert "if (phase === 3) ARENA.volleyCd = 0;" in DUNGEON_PAGE


def test_volley_every_ten_seconds():
    assert "ARENA.volleyCd = 10000;" in DUNGEON_PAGE
    assert "ARENA.volleyCd = 12000;" not in DUNGEON_PAGE


def test_boss_strafes_between_attacks():
    assert "Math.cos(ARENA.t * 1.7)" in DUNGEON_PAGE
    assert "Math.sin(ARENA.t * 1.3)" in DUNGEON_PAGE


def test_boss_and_minions_are_bigger():
    assert "-105, -180, 210, 210" in DUNGEON_PAGE   # босс
    assert "-36, -66, 72, 72" in DUNGEON_PAGE       # мобы
    # хитбоксы выросли вместе со спрайтами
    assert "a.y - (b.y - 60)) < 62" in DUNGEON_PAGE
    assert "a.y - (m.y - 26)) < 34" in DUNGEON_PAGE
