"""7Д открывается заслуженно: 50 уровень и пик 1 000 000 очков."""

import pathlib

from app import unlocks

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_locked_for_new_player():
    status = unlocks.check(1, 0)
    assert status["open"] is False
    assert "50" in unlocks.reason(status)


def test_needs_both_level_and_peak():
    assert unlocks.check(50, 999_999)["open"] is False
    assert unlocks.check(49, 5_000_000)["open"] is False
    assert unlocks.check(50, 1_000_000)["open"] is True
    assert unlocks.check(120, 2_000_000)["open"] is True


def test_reason_explains_what_is_missing():
    level_only = unlocks.reason(unlocks.check(10, 2_000_000))
    peak_only = unlocks.reason(unlocks.check(80, 10))
    assert "уровень" in level_only
    assert "1 000 000" in peak_only


def test_peak_is_tracked_in_schema():
    schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
    assert "peak_points bigint not null default 0" in schema
    assert "points_peak_trg" in schema


def test_gates_are_wired_in_server_and_bot():
    webapp = (ROOT / "app" / "webapp.py").read_text(encoding="utf-8")
    handlers = (ROOT / "app" / "handlers.py").read_text(encoding="utf-8")
    assert "await _d7_status(state, uid)" in webapp
    assert "unlocks_mod.check(progress[" + chr(34) + "level" + chr(34) + "]" in handlers
