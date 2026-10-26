"""Лидерборд, броня и хитбоксы на странице подземелья."""

from app.webapp import DUNGEON_PAGE


def test_leaderboard_is_wired():
    assert 'id="top"' in DUNGEON_PAGE
    assert "/api/dungeon/top" in DUNGEON_PAGE
    assert "function openTop(" in DUNGEON_PAGE
    assert "Лидерборд — заглушка" not in DUNGEON_PAGE
    assert 't === "board"' in DUNGEON_PAGE


def test_armor_button_is_wired():
    assert 'id="warmor"' in DUNGEON_PAGE
    assert "/api/dungeon/armor" in DUNGEON_PAGE
    assert "function heroArmor(" in DUNGEON_PAGE
    assert "HERO_ARMOR" in DUNGEON_PAGE
    assert "HERO_ARMOR.price" in DUNGEON_PAGE


def test_houses_have_hitboxes():
    assert "function blockedAt(" in DUNGEON_PAGE
    assert "function solidRects(" in DUNGEON_PAGE
    # движение и рывок проверяют стены
    assert "if (stuck || !blockedAt(nextX, P.y)) P.x = nextX;" in DUNGEON_PAGE
    assert "if (!blockedAt(dashX, P.y)) P.x = dashX;" in DUNGEON_PAGE
