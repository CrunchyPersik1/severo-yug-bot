"""Рассылка не дёргает тех, кто заблокировал бота."""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_dm_blocked_column_and_filter():
    schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
    assert "add column if not exists dm_blocked" in schema
    db = (ROOT / "app" / "db.py").read_text(encoding="utf-8")
    assert "where not dm_blocked" in db
    assert "async def mark_dm_blocked" in db


def test_forbidden_marks_player():
    src = (ROOT / "app" / "handlers.py").read_text(encoding="utf-8")
    start = src.index("async def broadcast_to_chats(")
    block = src[start:src.index("@router.message(Command(\"admin\"")]
    assert "TelegramForbiddenError" in block
    assert "await db.mark_dm_blocked(user_id)" in block
