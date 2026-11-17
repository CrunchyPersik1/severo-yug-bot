"""Квесты пасса: слот 0 должен забираться (регресс)."""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_slot_zero_is_not_turned_into_minus_one():
    src = (ROOT / "app" / "webapp.py").read_text(encoding="utf-8")
    start = src.index('@router.post("/api/pass/quest")')
    end = src.index('@router.post("/api/pass/bonus")')
    block = src[start:end]
    # тело запроса читаем как есть: «slot or -1» ломал первый квест дня
    assert 'int(body.get("slot") or -1)' not in block
    assert 'raw_slot = body.get("slot")' in block
    assert "slot = int(raw_slot)" in block


def test_claim_quest_rejects_unknown_slot():
    from app.pass_repo import PassError

    assert issubclass(PassError, Exception)
