"""Схема не должна ломаться на зарезервированных словах."""

import pathlib
import re


def _schema() -> str:
    return (pathlib.Path(__file__).resolve().parents[1] / "schema.sql").read_text(encoding="utf-8")


def test_stock_reroll_uses_safe_column_name():
    schema = _schema()
    block = re.search(r"create table if not exists stock_reroll ((.*?));", schema, re.S)
    assert block, "нет таблицы stock_reroll"
    body = block.group(1)
    # window — ключевое слово Postgres: startup падал с syntax error at or near "window"
    assert " win bigint" in body
    assert "window bigint" not in body
    assert "primary key (user_id, win)" in body


def test_queries_use_win_column():
    from app import webapp

    source = pathlib.Path(webapp.__file__).read_text(encoding="utf-8")
    assert "and win = $2" in source
    assert "on conflict (user_id, win)" in source
