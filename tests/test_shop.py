"""Магазин: каталог, промо-карты и описания учителей."""

import pytest

from app.cards import PROMO_ONLY_CARD_IDS
from app.shop import ShopError, catalog, find


def test_promo_cards_are_not_for_sale():
    skus = {entry.sku for entry in catalog()}
    for card_id in PROMO_ONLY_CARD_IDS:
        assert f"card:{card_id}" not in skus, "промо-карту нельзя купить в магазине"


def test_teacher_entries_have_descriptions():
    teachers = [entry for entry in catalog() if entry.kind == "card"]
    assert teachers
    assert all(entry.subtitle for entry in teachers)
    assert all("·" in entry.subtitle for entry in teachers), (
        "в подписи учителя должны быть роль и способность"
    )


def test_find_unknown_sku_raises():
    with pytest.raises(ShopError):
        find("card:no-such-teacher")
