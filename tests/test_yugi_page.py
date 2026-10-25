"""Кликер: печенька появилась на странице."""

from app.webapp import YUGI_PAGE


def test_golden_cookie_ui():
    assert 'id = "golden"' in YUGI_PAGE or 'id="golden"' in YUGI_PAGE
    assert "/api/yugi/golden" in YUGI_PAGE
    assert "Золотая печенька" in YUGI_PAGE
    assert "Безумие" in YUGI_PAGE
