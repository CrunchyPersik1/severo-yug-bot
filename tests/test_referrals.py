"""Реферальные ссылки: код, URL, статус и начисление попыток."""

import asyncio
from datetime import datetime, timedelta, timezone

from app import referrals


class FakeDB:
    def __init__(self, link=None) -> None:
        self.link = link
        self.inserted: list[tuple] = []
        self.claims: list[tuple] = []
        self.drop_grants: list[tuple] = []

    async def latest_ref_link(self, user_id: int):
        return self.link

    async def insert_ref_link(self, user_id: int, code: str, max_uses: int = 25):
        self.inserted.append((user_id, code, max_uses))
        return {"code": code, "owner_id": user_id, "uses": 0, "max_uses": max_uses, "active": True}

    async def claim_referral(self, referred_id: int, code: str):
        self.claims.append((referred_id, code))
        return {"owner_id": 777, "uses": 1, "max_uses": 25, "exhausted": False}

    async def grant_drop_limit(self, user_id: int, day, amount: int, default_limit: int = 1):
        self.drop_grants.append((user_id, amount))
        return 1


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple] = []

    async def send_message(self, chat_id: int, text: str):
        self.sent.append((chat_id, text))


def run(coro):
    return asyncio.run(coro)


def test_link_url_has_the_start_payload():
    assert referrals.link_url("severo_yug_bot", "abc12345") == (
        "https://t.me/severo_yug_bot?start=ref_abc12345"
    )


def test_make_code_is_url_safe():
    for _ in range(50):
        code = referrals.make_code()
        assert len(code) == 8
        assert all(c.isalnum() for c in code)


def test_status_creates_a_link():
    db = FakeDB()
    text = run(referrals.status(db, 1, "bot"))
    assert db.inserted and db.inserted[0][0] == 1
    assert "https://t.me/bot?start=ref_" in text


def test_status_reuses_a_recent_link():
    db = FakeDB(
        link={
            "code": "abc",
            "owner_id": 1,
            "uses": 3,
            "max_uses": 25,
            "active": True,
            "created_at": datetime.now(timezone.utc),
        }
    )
    text = run(referrals.status(db, 1, "bot"))
    assert not db.inserted
    assert "Приглашено" in text
    assert "https://t.me/bot?start=ref_abc" in text


def test_status_makes_a_new_link_after_a_week():
    old = datetime.now(timezone.utc) - timedelta(days=8)
    db = FakeDB(
        link={
            "code": "old",
            "owner_id": 1,
            "uses": 25,
            "max_uses": 25,
            "active": False,
            "created_at": old,
        }
    )
    text = run(referrals.status(db, 1, "bot"))
    assert db.inserted
    assert "https://t.me/bot?start=ref_" in text


def test_redeem_ignores_a_plain_start():
    db = FakeDB()
    assert run(referrals.redeem(db, FakeBot(), 42, "hello")) is None
    assert db.claims == []


def test_redeem_rewards_the_owner():
    db = FakeDB()
    bot = FakeBot()
    note = run(referrals.redeem(db, bot, 42, "ref_abc"))
    assert db.claims == [(42, "abc")]
    assert db.drop_grants == [(777, 1)]
    assert bot.sent and bot.sent[0][0] == 777
    assert note
