"""Админский журнал очков."""

def test_pointslog_command_exists():
    import inspect

    from app import handlers

    assert hasattr(handlers, "cmd_pointslog")
    source = inspect.getsource(handlers.cmd_pointslog)
    assert "points_log" in source
    assert "admin_ids" in source or "settings" in source
