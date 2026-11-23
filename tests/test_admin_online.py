"""Раздачи админа — только тем, кто сейчас в сети."""

import pathlib

from app import admin_actions

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_online_window_is_short():
    assert admin_actions.ONLINE_MINUTES == 5


def test_giveaway_branches_filter_by_presence():
    src = (ROOT / "app" / "admin_actions.py").read_text(encoding="utf-8")
    for name in ("act_points", "act_case", "act_card"):
        start = src.index("async def " + name + "(")
        end = src.index("async def ", start + 10)
        block = src[start:end]
        assert "_audience(con)" in block, name
        assert "any($2::bigint[])" in block or "any($3::bigint[])" in block, name


def test_online_command_reports_who_is_here():
    assert "online" in admin_actions.COMMANDS
    assert "онлайн" in admin_actions.COMMANDS
    assert "В сети" in admin_actions.HELP or "online" in admin_actions.HELP


def test_presence_is_written_by_app_and_bot():
    db = (ROOT / "app" / "db.py").read_text(encoding="utf-8")
    assert "last_seen = now()" in db
    assert "touch_presence" in db
    ban = (ROOT / "app" / "ban.py").read_text(encoding="utf-8")
    assert "touch_presence" in ban


def test_schema_has_last_seen():
    schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
    assert "add column if not exists last_seen" in schema
