"""Команда /pointsaudit: правки баланса на уровне базы."""

def test_pointsaudit_command_exists():
    import inspect

    from app import handlers

    source = inspect.getsource(handlers.cmd_pointsaudit)
    assert "points_audit" in source
    assert "db_user" in source
    assert "app_name" in source
