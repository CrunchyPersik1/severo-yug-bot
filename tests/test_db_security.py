"""Безопасность базы: публичные роли Supabase закрыты."""

import pathlib


def _schema() -> str:
    return (pathlib.Path(__file__).resolve().parents[1] / "schema.sql").read_text(encoding="utf-8")


def test_public_roles_have_no_access():
    schema = _schema()
    assert "revoke all on all tables in schema public from anon, authenticated" in schema
    assert "revoke all on all sequences in schema public from anon, authenticated" in schema
    # будущие таблицы тоже не должны унаследовать доступ
    assert "alter default privileges in schema public revoke all on tables" in schema


def test_rls_enabled_for_every_table():
    schema = _schema()
    assert "enable row level security" in schema
    assert "from pg_tables where schemaname = 'public'" in schema
