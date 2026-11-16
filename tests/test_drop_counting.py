"""Дроп из приложения должен попадать в drops (задания и мегаквест)."""

import pathlib

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "app" / "webapp.py"


def _api_drop() -> str:
    text = SOURCE.read_text(encoding="utf-8")
    start = text.index("async def api_drop(request: Request)")
    end = text.index("@router.", start + 10)
    return text[start:end]


def test_app_drop_writes_to_drops_table():
    body = _api_drop()
    assert "add_drop(uid, None, card.card_id, day)" in body


def test_second_drop_is_recorded_too():
    body = _api_drop()
    assert "add_drop(uid, None, second.card_id, day)" in body


def test_megaquest_counts_drops():
    from app import mega

    assert "from drops" in mega.QUESTS["drops"]["sql"]
