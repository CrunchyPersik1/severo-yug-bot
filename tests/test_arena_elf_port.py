"""Бой с боссом повторяет бой с эльфами: сердца, автоогонь, залпы."""

import pathlib

from app.webapp import DUNGEON_PAGE

IMAGES = pathlib.Path(__file__).resolve().parents[1] / "images" / "arena"


def test_hearts_heal_and_spawn():
    assert "ARENA.hearts" in DUNGEON_PAGE
    assert "ARENA.heartCd = 9 + Math.random() * 4;" in DUNGEON_PAGE
    assert "h1.hp = Math.min(h1.max, h1.hp + Math.round(h1.max * 0.22));" in DUNGEON_PAGE
    assert 'ctx.fillText("❤️"' in DUNGEON_PAGE


def test_auto_fire_on_hold_and_space():
    assert "ARENA.fire = true" in DUNGEON_PAGE
    assert "if (ARENA.fire) arenaAttack();" in DUNGEON_PAGE
    assert 'keys[" "]' in DUNGEON_PAGE


def test_boss_volley_only_in_last_phase():
    assert "if (b.phase >= 3){" in DUNGEON_PAGE
    assert "ARENA.volley = 4;" in DUNGEON_PAGE
    assert "ARENA.volleyNext = ARENA.t + 0.22;" in DUNGEON_PAGE


def test_attack_and_death_frames():
    assert "arenaBossSheet(ARENA.zi, bossState)" in DUNGEON_PAGE
    for name in ("mob_orc_atk.png", "mob_demon_atk.png", "mob_blood_atk.png", "mob_orc_death.png"):
        assert (IMAGES / name).exists(), name


def test_space_does_not_scroll():
    assert 'e.key === " "' in DUNGEON_PAGE and "preventDefault" in DUNGEON_PAGE
