"""Сброс 7Д: попытка не тратится, если коллекция закрыта."""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_gate_runs_before_claim():
    text = (ROOT / "app" / "webapp.py").read_text(encoding="utf-8")
    start = text.index("async def api_drop(request: Request)")
    body = text[start:start + 1600]
    gate = body.index("_d7_status(state, uid)")
    claim = body.index("claim_daily")
    assert gate < claim


def test_vip_limits_do_not_stack():
    from app.db import Database
    import inspect

    source = inspect.getsource(Database.vip_daily)
    assert "greatest(" in source
    assert "least(100" in source
    # старый вариант «прибавить к текущему»
    assert "grant_drop_limit(user_id, day_key(), 5" not in source
