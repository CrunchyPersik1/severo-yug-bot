"""Тайлсет для торговых точек на спавне."""

from app.webapp import DUNGEON_PAGE


def test_tiles_are_loaded():
    for name in ("furniture", "meat", "resources", "veg"):
        assert f"TILES.{name}.src" in DUNGEON_PAGE, name
    assert "/images/tiles/furniture.png" in DUNGEON_PAGE


def test_stalls_draw_sprites():
    assert "ctx.drawImage(TILES.furniture" in DUNGEON_PAGE
    assert "TILES.meat" in DUNGEON_PAGE
    assert "TILES.resources" in DUNGEON_PAGE
