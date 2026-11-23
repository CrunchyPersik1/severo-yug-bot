"""Кооп в арене: напарник, общий босс, позиции."""

import pathlib

from app.webapp import DUNGEON_PAGE

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_arena_accepts_coop_room():
    assert "function startArena(room){" in DUNGEON_PAGE
    assert "ARENA.coop = room || null;" in DUNGEON_PAGE
    assert "ARENA.boss.hp = room.hp;" in DUNGEON_PAGE


def test_position_and_damage_sync():
    assert '"/api/dungeon/boss/pos"' in DUNGEON_PAGE
    assert "ACOOP.pending += ARENA.dmg;" in DUNGEON_PAGE
    assert '"/api/dungeon/boss/hit", {damage: dmg}' in DUNGEON_PAGE


def test_remote_player_is_drawn():
    assert "ACOOP.remote" in DUNGEON_PAGE
    assert "напарник в кооп-арене" in DUNGEON_PAGE


def test_circle_no_longer_auto_starts_solo():
    assert "bossEngage(bs);" not in DUNGEON_PAGE.split("// раньше тут сразу стартовала соло-арена")[0][-400:]
    assert "// раньше тут сразу стартовала соло-арена — теперь спрашиваем режим" in DUNGEON_PAGE


def test_server_position_api():
    src = (ROOT / "app" / "webapp.py").read_text(encoding="utf-8")
    assert '@router.post("/api/dungeon/boss/pos")' in src
    repo = (ROOT / "app" / "dungeon_repo.py").read_text(encoding="utf-8")
    assert "async def move(" in repo
    assert '"x": float(row["px"])' in repo
