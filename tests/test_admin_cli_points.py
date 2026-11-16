"""Локальный CLI знает про журналы очков."""

def test_cli_has_pointslog_and_audit():
    from app import admin_actions

    assert "pointslog" in admin_actions.COMMANDS
    assert "pointsaudit" in admin_actions.COMMANDS
    assert "очкилог" in admin_actions.COMMANDS
    assert "аудит" in admin_actions.COMMANDS


def test_actions_query_our_tables():
    import inspect

    from app import admin_actions

    log_src = inspect.getsource(admin_actions.act_pointslog)
    audit_src = inspect.getsource(admin_actions.act_pointsaudit)
    assert "points_log" in log_src
    assert "points_audit" in audit_src
    # на пустой таблице не падаем, а объясняем
    assert "пусто" in log_src and "пусто" in audit_src
