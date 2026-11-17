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


def test_three_steps_in_order():
    text = SOURCE.read_text(encoding="utf-8")
    first = text.index("Вы уверены, что хотите сбросить прогресс?")
    second = text.index("Вы точно уверены?")
    third = text.index("Мы не уверены. Впишите слово")
    assert first < second < third


def test_no_native_dialogs_in_reset():
    # в Telegram-WebView confirm()/prompt() часто возвращают null,
    # поэтому сброс сделан собственной плашкой с полем ввода
    text = SOURCE.read_text(encoding="utf-8")
    start = text.index("function openResetDialog()")
    body = text[start:start + 6000]
    assert "confirm(" not in body
    assert "prompt(" not in body
    assert 'id="__r-word"' in body
    assert "RESET_WORD" in body


def test_word_is_checked_before_request():
    text = SOURCE.read_text(encoding="utf-8")
    start = text.index("function openResetDialog()")
    body = text[start:start + 6000]
    assert "word !== RESET_WORD" in body
    assert "/api/reset" in body


def test_api_requires_exact_word():
    text = WEBAPP.read_text(encoding="utf-8")
    start = text.index("async def api_reset")
    body = text[start:start + 900]
    assert 'RESET_WORD = "североюг"' in text
    assert "word != RESET_WORD" in body


def test_reset_wipes_gameplay_tables():
    source = inspect.getsource(Database.reset_progress)
    for table in ("collection", "cases", "stock_holdings", "pets_owned"):
        assert f'"{table}"' in source, table
    # подземелье остаётся: про него спрашиваем отдельно
    assert '"dungeon_hero"' not in source
    # аудит не трогаем
    assert '"game_log"' not in source
    assert '"points_log"' not in source
