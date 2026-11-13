"""Админ-панель: флаги игры и настройки конкретного чата."""

import asyncio
import inspect

import pytest

from app import admin_settings

CHAT = -1001234567890


class FakeDB:
    def __init__(self, values=None, chats=None):
        self.values = dict(values or {})
        self.chats = dict(chats or {})

    async def get_setting(self, key):
        return self.values.get(key)

    async def set_setting(self, key, value):
        self.values[key] = value

    async def chat_setting(self, chat_id, key):
        return self.chats.get((int(chat_id), key))

    async def set_chat_setting(self, chat_id, key, value):
        self.chats[(int(chat_id), key)] = value


def test_stock_alert_is_a_chat_setting():
    assert "alerts_stocks" in admin_settings.CHAT_BY_KEY
    assert "alerts_stocks" not in admin_settings.BY_KEY.keys() - admin_settings.CHAT_BY_KEY.keys()


def test_game_switches_are_global():
    for key in ("miniapps_live", "clicker_live", "shop_open", "mop_gems"):
        assert key in admin_settings.BY_KEY
        assert key not in admin_settings.CHAT_BY_KEY


def test_chat_defaults_to_on():
    db = FakeDB()
    assert asyncio.run(admin_settings.chat_on(db, CHAT, "alerts_stocks")) is True
    state = asyncio.run(admin_settings.load(db, CHAT))
    assert state["alerts_stocks"] is True


def test_global_defaults():
    state = asyncio.run(admin_settings.load(FakeDB()))
    assert state["miniapps_live"] is False
    assert state["shop_open"] is True
    assert state["mop_gems"] is True


def test_toggle_affects_only_that_chat():
    db = FakeDB()
    other = -1009999999999
    assert asyncio.run(admin_settings.toggle(db, CHAT, "alerts_stocks")) is False
    assert db.chats[(CHAT, "alerts_stocks")] == "0"
    # соседний чат не тронут
    assert (other, "alerts_stocks") not in db.chats
    assert asyncio.run(admin_settings.chat_on(db, other, "alerts_stocks")) is True
    # и глобальные флаги тоже не тронуты
    assert "alerts_stocks" not in db.values


def test_toggle_back_on():
    db = FakeDB(chats={(CHAT, "alerts_stocks"): "0"})
    assert asyncio.run(admin_settings.toggle(db, CHAT, "alerts_stocks")) is True
    assert db.chats[(CHAT, "alerts_stocks")] == "1"


def test_chat_setting_requires_chat():
    with pytest.raises(ValueError):
        asyncio.run(admin_settings.toggle(FakeDB(), None, "alerts_stocks"))


def test_global_toggle_writes_app_settings():
    db = FakeDB()
    assert asyncio.run(admin_settings.toggle(db, CHAT, "shop_open")) is False
    assert db.values["shop_open"] == "0"


def test_global_on_ignores_chat_keys():
    """Чат-флаг нельзя случайно прочитать как глобальный."""
    db = FakeDB(values={"alerts_stocks": "1"})
    assert asyncio.run(admin_settings.on(db, "alerts_stocks")) is False


def test_unknown_key_raises():
    with pytest.raises(ValueError):
        asyncio.run(admin_settings.toggle(FakeDB(), CHAT, "nope"))


def test_panel_shows_both_scopes():
    state = {"miniapps_live": True, "clicker_live": False, "shop_open": True,
             "alerts_stocks": False, "mop_gems": True}
    text = admin_settings.text(state, "Группа «Северо-Юг»")
    assert "Группа «Северо-Юг»" in text
    assert "ЭТОТ ЧАТ" in text and "ВСЯ ИГРА" in text
    assert "⛔" in text and "✅" in text
    markup = admin_settings.keyboard(state)
    buttons = [b for row in markup.inline_keyboard for b in row]
    assert len(buttons) == len(admin_settings.ITEMS) + 1
    assert any("· чат" in b.text for b in buttons)
    assert any("· игра" in b.text for b in buttons)


def test_broadcast_filters_by_chat():
    from app import stocks_alerts

    source = inspect.getsource(stocks_alerts.broadcast)
    assert "chats_alerts_off" in source
    assert "if int(user_id) in off:" in source
    assert "if int(chat_id) in off:" in source


def test_ticker_does_not_block_alerts_globally():
    """Раньше был один общий рубильник: теперь решает каждый чат."""
    import main

    source = inspect.getsource(main._ticker)
    assert "alerts_stocks" not in source


def test_bot_passes_chat_id_to_panel():
    from app import handlers

    source = inspect.getsource(handlers.cmd_admin)
    assert "admin_settings.load(db, chat.id)" in source
    callback = inspect.getsource(handlers.cb_admin_settings)
    assert "msg.chat.id" in callback
    assert "admin_settings.toggle(db, chat_id, key)" in callback


def test_game_checks_use_global_flags():
    from app import webapp

    assert 'admin_settings_mod.on(state.db, "shop_open")' in inspect.getsource(webapp.api_shop)
    assert 'admin_settings_mod.on(state.db, "mop_gems")' in inspect.getsource(webapp.api_mob_kill)


def test_chats_are_stored_separately():
    import app.db as db

    source = inspect.getsource(db.Database.chats_alerts_off)
    assert "chat_settings" in source
    assert "value = '0'" in source
