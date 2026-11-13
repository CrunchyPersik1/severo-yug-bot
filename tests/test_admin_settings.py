"""Админ-панель настроек: переключатели и их влияние."""

import asyncio
import inspect

import pytest

from app import admin_settings


class FakeDB:
    def __init__(self, values=None):
        self.values = dict(values or {})

    async def get_setting(self, key):
        return self.values.get(key)

    async def set_setting(self, key, value):
        self.values[key] = value


def test_panel_has_stock_alert_switch():
    keys = {item["key"] for item in admin_settings.ITEMS}
    assert "alerts_stocks" in keys
    assert "mop_gems" in keys
    assert "miniapps_live" in keys


def test_keys_are_unique():
    keys = [item["key"] for item in admin_settings.ITEMS]
    assert len(keys) == len(set(keys))


def test_load_uses_defaults_when_empty():
    state = asyncio.run(admin_settings.load(FakeDB()))
    assert state["alerts_stocks"] is True      # по умолчанию включено
    assert state["mop_gems"] is True
    assert state["miniapps_live"] is False     # по умолчанию закрыто


def test_toggle_flips_and_persists():
    db = FakeDB({"alerts_stocks": "1"})
    assert asyncio.run(admin_settings.on(db, "alerts_stocks")) is True
    assert asyncio.run(admin_settings.toggle(db, "alerts_stocks")) is False
    assert db.values["alerts_stocks"] == "0"
    assert asyncio.run(admin_settings.on(db, "alerts_stocks")) is False
    assert asyncio.run(admin_settings.toggle(db, "alerts_stocks")) is True


def test_toggle_unknown_key_raises():
    with pytest.raises(ValueError):
        asyncio.run(admin_settings.toggle(FakeDB(), "no_such_switch"))


def test_unknown_key_reads_as_off():
    assert asyncio.run(admin_settings.on(FakeDB(), "no_such_switch")) is False


def test_text_and_keyboard_show_state():
    state = {"miniapps_live": True, "clicker_live": False, "shop_open": True,
             "alerts_stocks": False, "mop_gems": True}
    text = admin_settings.text(state)
    assert "Настройки бота" in text
    assert "✅" in text and "⛔" in text
    markup = admin_settings.keyboard(state)
    buttons = [b for row in markup.inline_keyboard for b in row]
    assert len(buttons) == len(admin_settings.ITEMS) + 1
    datas = [b.callback_data for b in buttons]
    assert all(d.startswith("adm:s:") for d in datas)
    assert "adm:s:refresh" in datas
    assert any("Оповещения о бирже" in b.text for b in buttons)


def test_bot_has_settings_command_and_callback():
    from app import handlers

    source = inspect.getsource(handlers.cmd_admin)
    assert "admin_settings" in source
    assert '"settings"' in source
    callback = inspect.getsource(handlers.cb_admin_settings)
    assert "adm:s:" in callback
    assert "is_admin" in callback


def test_stock_alerts_respect_the_switch():
    import main

    source = inspect.getsource(main._ticker)
    assert 'admin_settings.on(db, "alerts_stocks")' in source


def test_shop_and_drops_respect_switches():
    from app import webapp

    shop = inspect.getsource(webapp.api_shop)
    assert 'admin_settings_mod.on(state.db, "shop_open")' in shop
    kill = inspect.getsource(webapp.api_mob_kill)
    assert 'admin_settings_mod.on(state.db, "mop_gems")' in kill


def test_help_mentions_settings():
    from app.admin_actions import HELP

    assert "settings" in HELP
