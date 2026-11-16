"""Стартовая схема не должна раздавать очки за коллекцию повторно."""

import pathlib
import re


def _schema() -> str:
    return (pathlib.Path(__file__).resolve().parents[1] / "schema.sql").read_text(encoding="utf-8")


def test_schema_does_not_backfill_points_on_startup():
    schema = _schema()
    # раньше этот UPDATE шёл при каждом старте и выдавал новым игрокам
    # стоимость коллекции ещё раз — то есть «мистические» очки
    assert "set bonus_points = bonus_points + coalesce(sub.total" not in schema
    # колонка-флаг осталась, как и пометка «досдача сделана»
    assert "points_backfilled = true" in schema


def test_points_audit_trigger_present():
    schema = _schema()
    assert "points_audit_trg" in schema
    assert "after update of bonus_points on players" in schema
