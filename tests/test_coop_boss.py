"""Кооп-босс: выбор режима у круга и рабочие ручки."""

import pathlib

from app.webapp import DUNGEON_PAGE

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_boss_circle_opens_mode_chooser():
    assert "function bossModeOpen()" in DUNGEON_PAGE
    assert "talkBtn.onclick = function(){ bossModeOpen(); };" in DUNGEON_PAGE
    assert 'id="bmsolo"' in DUNGEON_PAGE
    assert 'id="bmcoop"' in DUNGEON_PAGE


def test_coop_button_joins_room():
    assert "coopJoin(zoneIndex(P.y));" in DUNGEON_PAGE
    # соло по-прежнему запускает арену
    assert "startArena();" in DUNGEON_PAGE


def test_coop_endpoints_registered():
    src = (ROOT / "app" / "webapp.py").read_text(encoding="utf-8")
    for path in (
        "/api/dungeon/boss/join",
        "/api/dungeon/boss/state",
        "/api/dungeon/boss/hit",
        "/api/dungeon/boss/start",
        "/api/dungeon/boss/leave",
    ):
        assert '@router.post("' + path + '")' in src or '@router.get("' + path + '")' in src


def test_two_players_max():
    from app import dungeon

    assert dungeon.MAX_PLAYERS == 2
