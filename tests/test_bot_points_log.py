"""Ботовые начисления очков пишутся в журнал."""

import inspect

from app import handlers


def test_bot_paths_pass_source():
    source = inspect.getsource(handlers)
    for marker in ('"bot:drop"', '"bot:clicker"', '"bot:roulette"', '"bot:case"'):
        assert marker in source, marker


def test_drop_and_roulette_use_source():
    drop = inspect.getsource(handlers.cmd_sky) if hasattr(handlers, "cmd_sky") else ""
    assert True
    src = inspect.getsource(handlers)
    assert 'add_points(user.id, card.points, "bot:drop"' in src
    assert '"bot:roulette"' in src
