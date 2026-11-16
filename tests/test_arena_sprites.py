"""Арена боссов: спрайты из новых паков и кадры по сетке."""

import pathlib

from app.webapp import DUNGEON_PAGE

IMAGES = pathlib.Path(__file__).resolve().parents[1] / "images" / "arena"

EXPECTED = (
    "hero_knight.png",
    "hero_thief.png",
    "hero_anomaly.png",
    "boss_dead.png",
    "mob_orc.png",
    "mob_soldier.png",
    "mob_demon.png",
    "mob_blood.png",
    "arrow.png",
)


def test_sprite_files_exist():
    for name in EXPECTED:
        path = IMAGES / name
        assert path.exists(), name
        assert path.stat().st_size > 200, name


def test_hero_sprite_depends_on_weapon_kind():
    assert "function arenaHeroSheet()" in DUNGEON_PAGE
    body = DUNGEON_PAGE[DUNGEON_PAGE.index("function arenaHeroSheet()"):][:600]
    assert 'kind === "bow"' in body and 'kind === "staff"' in body


def test_boss_sprite_cycles_by_zone():
    assert "function arenaBossSheet(zi)" in DUNGEON_PAGE
    assert "ARENA_BOSS_SHEETS" in DUNGEON_PAGE
    assert "arenaBossSheet(ARENA.zi)" in DUNGEON_PAGE


def test_frames_are_sliced_not_stretched():
    # drawImage с источником-кадром, а не растяжением всего листа
    assert "bs * bossSheet.fw" in DUNGEON_PAGE
    assert "hs * heroSheet.fw" in DUNGEON_PAGE
    assert "imageSmoothingEnabled = false" in DUNGEON_PAGE
