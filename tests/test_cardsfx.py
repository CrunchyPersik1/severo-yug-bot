"""Визуальный отклик карточки: уровни, декор и цвета."""

import pytest

from app import cardsfx
from app.cards import CARDS, RARITIES


def test_every_rarity_has_a_level():
    for key in RARITIES:
        assert isinstance(cardsfx.level(key), int)


def test_rare_is_plain_and_ultra_is_loud():
    assert cardsfx.level("rare") == 0
    assert cardsfx.level("superrare") == 0
    assert cardsfx.level("ultra") == 5
    assert cardsfx.level("ultra") > cardsfx.level("epic") > 0


def test_levels_never_exceed_max():
    for key in RARITIES:
        assert 0 <= cardsfx.level(key) <= cardsfx.MAX_LEVEL


def test_unknown_rarity_is_treated_as_common():
    assert cardsfx.level("nope") == 0
    assert cardsfx.decor("nope") == []
    assert cardsfx.color("nope").startswith("#")


def test_decor_grows_with_level():
    rare = cardsfx.decor("rare")
    legendary = cardsfx.decor("legendary")
    ultra = cardsfx.decor("ultra")
    assert rare == []
    assert set(rare) < set(legendary) < set(ultra)
    assert "crown" in ultra


def test_fullscreen_only_for_top_rarities():
    assert cardsfx.fullscreen("legendary") is False
    assert cardsfx.fullscreen("ultimate") is True
    assert cardsfx.fullscreen("ultra") is True


def test_payload_shape():
    data = cardsfx.payload("ultra")
    assert data["level"] == 5
    assert data["color"].startswith("#")
    assert data["reveal_ms"] >= 1000
    assert data["title"] == "Ультралегендарный"
    assert data["emoji"]


def test_every_card_in_catalog_gets_a_payload():
    for card in CARDS:
        data = cardsfx.payload(card.rarity)
        assert data["level"] in range(0, cardsfx.MAX_LEVEL + 1)
