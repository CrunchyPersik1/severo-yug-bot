"""case full — раздача всем, включая офлайн."""

import pathlib

from app import admin_actions

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_full_keyword_is_recognised():
    src = (ROOT / "app" / "admin_actions.py").read_text(encoding="utf-8")
    start = src.index("async def act_case(")
    end = src.index("async def act_card(")
    block = src[start:end]
    assert '("full", "фул", "всем", "все")' in block
    assert "if everyone:" in block
    # full идёт без фильтра присутствия
    everyone_branch = block[block.index("if everyone:"):]
    assert "cross join generate_series(1, $1)" in everyone_branch
    assert "any($" not in everyone_branch.split("total = int")[0]


def test_full_is_not_treated_as_nickname():
    src = (ROOT / "app" / "admin_actions.py").read_text(encoding="utf-8")
    start = src.index("async def act_case(")
    block = src[start:src.index("async def act_card(")]
    assert 'named = [arg for arg in named if arg.lower() not in ("full"' in block


def test_help_mentions_full():
    assert "case full" in admin_actions.HELP
