"""Аудит очков на уровне БД: триггер ловит и ручной SQL."""

import pathlib


def _schema() -> str:
    return (pathlib.Path(__file__).resolve().parents[1] / "schema.sql").read_text(encoding="utf-8")


def test_schema_has_points_audit_trigger():
    schema = _schema()
    assert "create table if not exists points_audit" in schema
    assert "create or replace function points_audit_fn" in schema
    assert "after update of bonus_points on players" in schema
    # триггер пересоздаётся, поэтому повторный деплой не падает
    assert "drop trigger if exists points_audit_trg on players" in schema
