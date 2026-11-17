"""Сброс аккаунта не трогает подземелье, но спрашивает про него."""

import inspect
import pathlib

from app.db import Database
from app.webapp import DUNGEON_PAGE

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_reset_keeps_dungeon_tables():
    source = inspect.getsource(Database.reset_progress)
    for table in ("dungeon_hero", "dungeon_shop_bought", "dungeon_quest"):
        assert f'"{table}"' not in source, table


def test_reset_sets_ask_flag():
    source = inspect.getsource(Database.reset_progress)
    assert "dungeon_reset_ask" in source


def test_dungeon_page_has_reset_question():
    assert 'id="dunreset"' in DUNGEON_PAGE
    assert "Сбросить подземелье" in DUNGEON_PAGE
    assert 'id="drno"' in DUNGEON_PAGE and 'id="dryes"' in DUNGEON_PAGE


def _ask_block() -> str:
    start = DUNGEON_PAGE.index("function bindDungeonResetAsk()")
    return DUNGEON_PAGE[start:start + 800]


def test_question_confirms_before_wiping():
    body = _ask_block()
    assert "confirm(" in body
    assert "/api/dungeon/reset" in body


def test_decline_keeps_progress():
    body = _ask_block()
    assert "reset: false" in body


def test_api_dungeon_reset_exists():
    text = (ROOT / "app" / "webapp.py").read_text(encoding="utf-8")
    assert '"/api/dungeon/reset"' in text
