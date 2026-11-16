"""Кадры героя и подсчёт открытых кейсов в мегаквесте."""

import pathlib

from app import mega
from app.webapp import DUNGEON_PAGE

IMAGES = pathlib.Path(__file__).resolve().parents[1] / "images" / "arena"


def test_hero_strips_are_presliced():
    for cls in ("knight", "thief", "anomaly"):
        for state in ("idle", "atk"):
            path = IMAGES / ("hero_%s_%s.png" % (cls, state))
            assert path.exists(), path.name


def test_hero_draw_uses_state_sheet():
    assert 'const heroState = h1.hurt > 0 ? "hurt" : (h1.atkCd > 0.12 ? "atk" : "idle");' in DUNGEON_PAGE
    assert "arenaHeroSheet(heroState)" in DUNGEON_PAGE
    assert "112, 80, 3" not in DUNGEON_PAGE


def test_mega_counts_cases_by_open_time():
    sql = mega.QUESTS["drops"]["sql"]
    assert "coalesce(opened_at, created_at)" in sql


def test_schema_has_opened_at():
    schema = (pathlib.Path(__file__).resolve().parents[1] / "schema.sql").read_text(encoding="utf-8")
    assert "add column if not exists opened_at timestamptz" in schema
    assert "update cases set opened_at = created_at where opened" in schema


def test_open_case_sets_opened_at():
    import inspect

    from app.db import Database

    source = inspect.getsource(Database.open_case)
    assert "opened_at = now()" in source
