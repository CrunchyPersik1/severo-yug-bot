"""Рассылка /admin soo: группы и личка каждому игроку."""

import asyncio
import pathlib

from app import handlers

ROOT = pathlib.Path(__file__).resolve().parents[1]


class FakeBot:
    def __init__(self, fail=()):
        self.sent: list[int] = []
        self.fail = set(fail)

    async def send_message(self, chat_id, text, **kwargs):
        if chat_id in self.fail:
            raise RuntimeError("нет доступа")
        self.sent.append(int(chat_id))


class FakeDb:
    def __init__(self, groups, players):
        self.groups = groups
        self.players = players
        self.left: list[int] = []

    async def broadcast_targets(self):
        return list(self.groups)

    async def broadcast_players(self):
        return list(self.players)

    async def mark_chat_left(self, chat_id):
        self.left.append(chat_id)


def run(coro):
    return asyncio.run(coro)


def test_broadcast_goes_to_groups_and_private():
    bot = FakeBot()
    db = FakeDb(groups=[-1001, -1002], players=[11, 12, 13])
    text = run(handlers.broadcast_to_chats(bot, db, "привет"))
    assert bot.sent == [-1001, -1002, 11, 12, 13]
    assert "Группы: <b>2</b>" in text
    assert "Лички: <b>3</b> из 3" in text


def test_broadcast_counts_unreachable_dm():
    bot = FakeBot(fail=(12,))
    db = FakeDb(groups=[], players=[11, 12])
    text = run(handlers.broadcast_to_chats(bot, db, "тест"))
    assert "Лички: <b>1</b> из 2" in text
    assert "не дошло 1" in text


def test_broadcast_marks_dead_group_left():
    bot = FakeBot(fail=(-1009,))
    db = FakeDb(groups=[-1009], players=[])
    run(handlers.broadcast_to_chats(bot, db, "тест"))
    assert db.left == [-1009]


def test_command_text_mentions_private():
    src = (ROOT / "app" / "handlers.py").read_text(encoding="utf-8")
    assert "Разошлю в группы с ботом и в личку каждому игроку." in src
    assert "async def broadcast_players" in (ROOT / "app" / "db.py").read_text(encoding="utf-8")
