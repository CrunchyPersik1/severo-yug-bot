"""Живой лог игры: запись событий, разбор апдейтов, чтение ленты."""

import asyncio
import datetime as dt
import inspect

import pytest

from app import game_log


class FakeCon:
    """Заглушка соединения: запоминает SQL и параметры."""

    def __init__(self, rows=None):
        self.calls = []
        self._rows = rows or []

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        return "INSERT 0 1"

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return self._rows


class FakePool:
    def __init__(self, con):
        self.con = con

    def acquire(self):
        con = self.con

        class _Ctx:
            async def __aenter__(self):
                return con

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


def test_who_of_prefers_name_and_nick():
    assert game_log.who_of("troxa25", "Тро", 1) == "Тро (@troxa25)"
    assert game_log.who_of("troxa25", None, 1) == "@troxa25"
    assert game_log.who_of(None, "Тро", 1) == "Тро"
    assert game_log.who_of(None, None, 42) == "id42"


def test_clean_strips_markup_escapes_and_newlines():
    assert game_log.clean("<b>жирный</b>  текст\n\nс переносом") == "жирный текст с переносом"
    # Экранированный тег — тоже тег: сначала unescape, потом снимаем.
    assert game_log.clean("&lt;b&gt;не тег&lt;/b&gt;") == "не тег"
    assert game_log.clean("обычный <3 текст") == "обычный <3 текст"
    assert game_log.clean(None) == ""


def test_clean_cuts_long_text():
    long_text = "я" * 500
    result = game_log.clean(long_text, limit=50)
    assert len(result) == 50
    assert result.endswith("…")


def test_write_never_raises_even_when_db_is_broken():
    """Лог не имеет права ломать игру: ошибка записи глотается."""

    class Broken:
        def acquire(self):
            raise RuntimeError("база легла")

    # Никакого исключения наружу — это и есть контракт.
    asyncio.run(game_log.write(Broken(), 1, "кто-то", "app", "действие", ""))


def test_write_stores_expected_columns():
    con = FakeCon()
    asyncio.run(game_log.write(FakePool(con), 7, "Тро", "app", "открыл кейс", "кейс 7Г"))
    assert len(con.calls) == 1
    sql, args = con.calls[0]
    assert "insert into game_log" in sql
    assert args == (7, "Тро", "app", "открыл кейс", "кейс 7Г")


def test_write_soon_schedules_without_waiting():
    """Горячий путь не должен ждать базу: запись уходит в фон."""

    async def run():
        con = FakeCon()
        game_log.write_soon(FakePool(con), 1, "Тро", "app", "кликает", "")
        # Сразу после вызова записи ещё нет — она в фоне.
        await asyncio.sleep(0.05)
        return con.calls

    calls = asyncio.run(run())
    assert len(calls) == 1


def test_describe_update_reads_commands():
    class User:
        id = 10
        username = "troxa25"
        first_name = "Тро"
        is_bot = False

    class Chat:
        type = "private"

    class Message:
        from_user = User()
        chat = Chat()
        text = "/drop@SeveroYug_bot"
        web_app_data = None

    class Update:
        message = Message()
        edited_message = None
        callback_query = None

    entry = game_log.describe_update(Update())
    assert entry is not None
    user_id, who, action, detail = entry
    assert user_id == 10
    assert who == "Тро (@troxa25)"
    assert action == "команда /drop"
    assert "личка" in detail


def test_describe_update_reads_buttons():
    class User:
        id = 11
        username = None
        first_name = "Игрок"
        is_bot = False

    class Query:
        from_user = User()
        data = "drop:roll"

    class Update:
        message = None
        edited_message = None
        callback_query = Query()

    entry = game_log.describe_update(Update())
    assert entry is not None
    assert entry[2] == "кнопка крутка «Северо-Юг»"
    assert entry[3] == "drop:roll"


def test_describe_update_skips_bots_and_service_updates():
    class Update:
        message = None
        edited_message = None
        callback_query = None

    assert game_log.describe_update(Update()) is None


def test_recent_clamps_arguments():
    """Огромный лимит из консоли не должен выгружать весь лог."""

    async def run():
        con = FakeCon(rows=[])
        await game_log.recent(con, minutes=999999, limit=99999)
        return con.calls[-1][1]

    args = asyncio.run(run())
    minutes, limit = args[0], args[1]
    assert minutes <= 60 * 24 * 7
    assert limit <= 500


def test_line_is_readable():
    row = {
        "id": 1,
        "user_id": 5,
        "who": "Тро (@troxa25)",
        "source": "app",
        "action": "открыл кейс",
        "detail": "кейс 7Г",
        "created_at": dt.datetime(2026, 11, 13, 12, 30, 5, tzinfo=dt.timezone.utc),
    }
    text = game_log.line(row)
    assert "Тро (@troxa25)" in text
    assert "[приложение]" in text
    assert "открыл кейс" in text
    assert "кейс 7Г" in text


def test_line_falls_back_to_id_when_name_missing():
    row = {
        "id": 1,
        "user_id": 77,
        "who": "",
        "source": "bot",
        "action": "сообщение",
        "detail": "",
        "created_at": None,
    }
    assert "id77" in game_log.line(row)


def test_log_command_is_registered():
    from app import admin_actions

    assert "log" in admin_actions.COMMANDS
    assert "лог" in admin_actions.COMMANDS
    assert admin_actions.COMMANDS["log"] is admin_actions.act_log


def test_log_command_is_defined_before_the_table():
    """Регрессия: NameError — act_log объявили ниже COMMANDS."""
    from app import admin_actions

    source = inspect.getsource(admin_actions)
    assert source.index("async def act_log") < source.index("\nCOMMANDS = {")


def test_webhook_writes_to_the_log():
    """Апдейт бота должен попадать в ленту, иначе смотреть нечего."""
    import main

    source = inspect.getsource(main.telegram_webhook)
    assert "game_log.describe_update" in source
    assert "game_log.write_soon" in source


def test_miniapp_actions_reach_the_log():
    """40 ручек мини-аппки идут через _player — ловим их там."""
    from app import webapp

    source = inspect.getsource(webapp._player)
    assert "_log_action" in source


def test_logging_covers_main_actions():
    from app import webapp

    for path in (
        "/api/case/open",
        "/api/roulette/spin",
        "/api/casino/play",
        "/api/market/buy",
        "/api/quests/claim",
        "/api/dungeon/quest",
        "/api/yugi/tap",
    ):
        assert path in webapp._ACTIONS, path


def test_noisy_handlers_are_throttled():
    """Тапы кликера не должны забивать ленту целиком."""
    from app import webapp

    assert "/api/yugi/tap" in webapp._STORM
    assert "/api/dungeon/presence" in webapp._STORM
    assert webapp.STORM_SECONDS >= 5


def test_schema_has_game_log():
    import io

    schema = io.open("schema.sql", encoding="utf-8").read()
    assert "create table if not exists game_log" in schema
    assert "game_log_created_idx" in schema
    assert "game_log_user_idx" in schema


def test_prune_keeps_a_week():
    assert game_log.KEEP_DAYS >= 1
