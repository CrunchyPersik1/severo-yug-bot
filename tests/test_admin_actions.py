"""Админ-выдача кейсов: всем и лично игроку."""

import asyncio

from app import admin_actions


class FakeCon:
    def __init__(self, player=None) -> None:
        self.player = player
        self.executed: list[tuple] = []

    async def fetchrow(self, query: str, *args):
        if self.player is not None:
            return self.player
        return None

    async def fetch(self, query: str, *args):
        return []

    async def fetchval(self, query: str, *args):
        if "count(*) from players" in query:
            return 3
        return 0

    async def execute(self, query: str, *args):
        self.executed.append((query, args))


def run(coro):
    return asyncio.run(coro)


def test_case_for_everyone():
    con = FakeCon()
    text = run(admin_actions.act_case(con, ["5"]))
    assert "3" in text and "5" in text
    assert con.executed, "должен выдать кейсы всем"


def test_case_for_one_player():
    con = FakeCon(player={"user_id": 42, "first_name": "Друг", "username": None})
    text = run(admin_actions.act_case(con, ["@друг", "5"]))
    assert "Друг" in text and "5" in text
    assert con.executed[0][1] == (42, 5)


def test_case_arguments_order_does_not_matter():
    con = FakeCon(player={"user_id": 42, "first_name": "Друг", "username": None})
    run(admin_actions.act_case(con, ["5", "@друг"]))
    assert con.executed[0][1] == (42, 5)
