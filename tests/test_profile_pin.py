"""Карточку в профиль можно вешать из обеих коллекций."""

import pathlib

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "app" / "webapp.py"


def _pin_endpoint() -> str:
    text = SOURCE.read_text(encoding="utf-8")
    start = text.index("async def api_profile_pin")
    end = text.index("@router.", start + 10)
    return text[start:end]


def test_pin_accepts_7d_cards():
    body = _pin_endpoint()
    # коллекция 7Д лежит в отдельном справочнике, раньше такие карты
    # отбивались ответом «Такой карты нет»
    assert "cards_d_mod.CARDS_D_BY_ID" in body
    assert "cards.CARDS_D_BY_ID" not in body


def test_pin_still_rejects_unknown_card():
    body = _pin_endpoint()
    assert "Такой карты нет" in body


def test_pin_returns_card_payload_for_both():
    body = _pin_endpoint()
    assert "CARDS_BY_ID.get(card_id) or cards_d_mod.CARDS_D_BY_ID.get(card_id)" in body
