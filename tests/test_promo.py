"""Промокоды: карты, очки и дополнительные попытки «Северо-Юг»."""

import asyncio

import pytest

from app import promo
from app.cards import get_card


class FakeDB:
    def __init__(self) -> None:
        self.used: set[str] = set()
        self.cards: list[str] = []
        self.points = 0
        self.drop_amount = 0
        self.drop_left = 0

    async def redeem_promo(self, user_id: int, code: str) -> bool:
        if code in self.used:
            return False
        self.used.add(code)
        return True

    async def add_card(self, user_id: int, card_id: str) -> int:
        self.cards.append(card_id)
        return 1

    async def add_points(self, user_id: int, amount: int) -> int:
        self.points += int(amount)
        return self.points

    async def grant_drop_limit(
        self, user_id: int, day, amount: int, default_limit: int = 1
    ) -> int:
        self.drop_amount = int(amount)
        self.drop_left = int(default_limit) + int(amount)
        return self.drop_left


def run(coro):
    return asyncio.run(coro)


def test_promo_keys_are_already_normalized():
    for key in promo.PROMOS:
        assert promo.normalize(key) == key, key


def test_unknown_code_is_rejected():
    with pytest.raises(promo.PromoError):
        run(promo.redeem(FakeDB(), 1, "no-such-code"))


def test_mishainpotato_gives_free_misha_with_points():
    db = FakeDB()
    text = run(promo.redeem(db, 1, "MISHAINPOTATO"))
    assert db.cards == ["misha"]
    assert db.points == get_card("misha").points
    assert "Промокод принят" in text


def test_mishakotletka_gives_points():
    db = FakeDB()
    run(promo.redeem(db, 1, "mishakotletka"))
    assert db.points == 15000
    assert db.cards == []


def test_severo_yun_gives_drop_attempts():
    db = FakeDB()
    text = run(promo.redeem(db, 1, "северо юн"))
    assert db.drop_amount == 5
    assert "Попыток" in text or "попыток" in text


def test_promo_can_be_used_only_once():
    db = FakeDB()
    run(promo.redeem(db, 1, "mishakotletka"))
    with pytest.raises(promo.PromoError):
        run(promo.redeem(db, 1, "mishakotletka"))
