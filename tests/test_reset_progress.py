"""Сброс прогресса: три подтверждения и контрольное слово."""

import inspect
import pathlib

from app.db import Database

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "app" / "webtheme.py"
WEBAPP = pathlib.Path(__file__).resolve().parents[1] / "app" / "webapp.py"


def test_reset_button_exists_in_settings():
    text = SOURCE.read_text(encoding="utf-8")
    assert 'id="__reset"' in text
    assert "Сбросить прогресс" in text


def test_three_confirmations_in_order():
    text = SOURCE.read_text(encoding="utf-8")
    start = text.index('getElementById("__reset")')
    body = text[start:start + 1400]
    first = body.index("Вы уверены, что хотите сбросить прогресс?")
    second = body.index("Вы точно уверены?")
    third = body.index("Мы не уверены. Впишите слово")
    assert first < second < third


def test_word_is_checked_before_request():
    text = SOURCE.read_text(encoding="utf-8")
    start = text.index('getElementById("__reset")')
    body = text[start:start + 1600]
    assert '!== "североюг"' in body
    assert '/api/reset' in body


def test_api_requires_exact_word():
    text = WEBAPP.read_text(encoding="utf-8")
    start = text.index("async def api_reset")
    body = text[start:start + 900]
    assert 'RESET_WORD = "североюг"' in text
    assert "word != RESET_WORD" in body


def test_reset_wipes_gameplay_tables():
    source = inspect.getsource(Database.reset_progress)
    for table in ("collection", "cases", "dungeon_hero", "stock_holdings", "pets_owned"):
        assert f'"{table}"' in source, table
    # аудит не трогаем
    assert '"game_log"' not in source
    assert '"points_log"' not in source
