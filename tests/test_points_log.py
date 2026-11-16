"""Журнал очков: чтобы отвечать «откуда баланс»."""

import pathlib
import re

from app.db import Database


def _schema() -> str:
    return (pathlib.Path(__file__).resolve().parents[1] / "schema.sql").read_text(encoding="utf-8")


def test_points_log_table_exists():
    schema = _schema()
    assert "create table if not exists points_log" in schema
    assert "source text not null" in schema
    assert "points_log_user_idx" in schema


def test_add_points_takes_source_and_logs():
    import inspect

    source = inspect.getsource(Database.add_points)
    assert "log_points" in source
    assert "source:" in source


def test_admin_points_are_logged():
    from app import admin_actions

    text = pathlib.Path(admin_actions.__file__).read_text(encoding="utf-8")
    assert "insert into points_log" in text
    assert "'admin'" in text
