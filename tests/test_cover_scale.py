"""Укрытия масштабируются и держат выстрелы; игроков видно везде."""

from app.webapp import DUNGEON_PAGE


def test_cover_stored_as_fractions():
    assert "ARENA.cover = [" in DUNGEON_PAGE
    body = DUNGEON_PAGE[DUNGEON_PAGE.index("ARENA.cover = ["):][:320]
    assert "fx:" in body and "fw:" in body
    assert "x: w * 0.22" not in body


def test_cover_scales_with_canvas():
    assert "function arenaCoverRect(c)" in DUNGEON_PAGE
    rect = DUNGEON_PAGE[DUNGEON_PAGE.index("function arenaCoverRect(c)"):][:260]
    assert "c.fx * w" in rect and "c.fw * w" in rect
    assert "ARENA.w = w; ARENA.h = h;" in DUNGEON_PAGE


def test_player_shots_stop_at_cover():
    block = DUNGEON_PAGE[DUNGEON_PAGE.index("ARENA.shots = (ARENA.shots || [])"):][:400]
    assert "if (arenaBlocked(a.x, a.y, 2)) return false;" in block


def test_remote_players_are_not_zone_filtered():
    import pathlib

    source = pathlib.Path(__file__).resolve().parents[1] / "app" / "dungeon_hub.py"
    text = source.read_text(encoding="utf-8")
    assert "abs(spot.zone - base_zone) > 1" not in text


def test_offscreen_players_marked():
    assert "if ((sx < 0 || sy < 0 || sx > w || sy > h) && r.name){" in DUNGEON_PAGE
