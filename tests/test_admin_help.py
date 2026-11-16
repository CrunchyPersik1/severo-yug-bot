"""Сводка админки и меню команд должны быть полными."""

from app import admin_actions, commands


def test_help_mentions_key_sections():
    help_text = admin_actions.HELP
    for section in ("СВОДКА И ИГРОКИ", "ВЫДАЧА ИГРОКАМ", "БИРЖА",
                    "РЕЖИМЫ И РАССЫЛКА", "МОДЕРАЦИЯ"):
        assert section in help_text, section
    # новые команды аудита и обучение
    assert "pointslog" in help_text
    assert "pointsaudit" in help_text


def test_help_lists_every_action():
    help_text = admin_actions.HELP
    for name in admin_actions.COMMANDS:
        if name in ("курс", "лог", "тема", "очкилог", "аудит"):
            continue  # это алиасы
        assert name in help_text, name


def test_command_menus_are_sane():
    player = {c.command for c in commands.COMMANDS}
    admin = {c.command for c in commands.ADMIN_COMMANDS}
    assert len(player) == len(commands.COMMANDS), "дубли в меню игрока"
    assert "tutorial" in player
    assert "admin" not in player
    assert "admin" in admin
    assert "pointsaudit" in admin
    assert len(commands.ADMIN_COMMANDS) <= 100, "Telegram не примет больше 100"


def test_command_descriptions_fit_limits():
    for cmd in commands.ADMIN_COMMANDS:
        assert len(cmd.description) <= 256
        assert cmd.command.isascii(), cmd.command
