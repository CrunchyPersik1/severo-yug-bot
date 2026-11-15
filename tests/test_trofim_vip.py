"""Тема Трофима и VIP-лимиты казино."""

from app import casino, themes


def test_trofim_detected_by_name_and_env(monkeypatch):
    assert themes.is_trofim(5, "troxa25", None) is True
    assert themes.is_trofim(5, "@troxa25", None) is True
    assert themes.is_trofim(5, "trofim_x", None) is True
    assert themes.is_trofim(5, None, "Трофим") is True
    assert themes.is_trofim(5, "vasya", "Вася") is False
    monkeypatch.setenv("TROFIM_IDS", "777")
    assert themes.is_trofim(777, "vasya", None) is True
    assert themes.is_trofim(778, "vasya", None) is False


def test_trofim_command_and_autogrant_exist():
    import inspect

    from app import handlers

    assert hasattr(handlers, "cmd_trofim")
    source = inspect.getsource(handlers.cmd_start_menu)
    assert "is_trofim" in source
    assert "grant_theme" in source


def test_vip_casino_limit_is_higher():
    assert casino.VIP_MAX_BET > casino.MAX_BET
    assert casino.VIP_MAX_BET == 1_000_000


def test_web_casino_uses_vip_limit():
    import inspect

    from app import webapp

    source = inspect.getsource(webapp)
    assert "_casino_max_bet" in source
    assert "casino.VIP_MAX_BET" in source
