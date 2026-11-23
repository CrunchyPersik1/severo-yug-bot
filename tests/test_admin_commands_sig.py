"""Каждая админ-команда принимает (con, args) — иначе бот падает."""

import inspect
import pathlib

from app import admin_actions


def test_every_command_has_two_parameters():
    bad = [
        name
        for name, func in admin_actions.COMMANDS.items()
        if len(inspect.signature(func).parameters) != 2
    ]
    assert not bad, bad


def test_online_wrapper_present():
    src = pathlib.Path(admin_actions.__file__).read_text(encoding="utf-8")
    assert "async def act_online(con: asyncpg.Connection, args: list[str]) -> str:" in src
    assert '"online": act_online' in src
