"""Оффлайн-игроки в углу локации."""

from app.webapp import DUNGEON_PAGE
from app.dungeon_hero import DungeonHeroRepo


def test_offline_is_drawn_in_corner():
    assert "function drawOffline(" in DUNGEON_PAGE
    assert "function drawOfflineAll(" in DUNGEON_PAGE
    assert "OFFLINE" in DUNGEON_PAGE
    assert "applyOffline(" in DUNGEON_PAGE
    # подписи и засыпание на месте
    assert "zZz" in DUNGEON_PAGE or '"z"' in DUNGEON_PAGE


def test_offline_comes_from_socket_and_http():
    assert "applyOffline(data.offline)" in DUNGEON_PAGE
    assert "offline" in DUNGEON_PAGE


def test_wake_up_on_own_spot():
    assert "проснуться там, где уснул" in DUNGEON_PAGE
    assert "hero.zone != null" in DUNGEON_PAGE


def test_repo_has_offline_helpers():
    assert hasattr(DungeonHeroRepo, "save_spot")
    assert hasattr(DungeonHeroRepo, "offline")
