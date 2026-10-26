"""Квест НПС: правила, выдача, страница."""

from datetime import datetime, timedelta, timezone

from app import dungeon
from app.webapp import DUNGEON_PAGE

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def test_quest_is_stable_within_hour():
    keys = ("hour", "kind", "zone", "need", "coins", "xp")
    first = {k: dungeon.quest_for(42, 5, NOW)[k] for k in keys}
    again = {k: dungeon.quest_for(42, 5, NOW + timedelta(minutes=20))[k] for k in keys}
    assert first == again
    # в следующий час квест другой
    later = dungeon.quest_for(42, 5, NOW + timedelta(hours=1))
    assert later["hour"] == first["hour"] + 1
    # таймер до смены убывает
    assert dungeon.quest_for(42, 5, NOW + timedelta(minutes=20))["expires_in"] < \
        dungeon.quest_for(42, 5, NOW)["expires_in"]


def test_quest_scales_with_level():
    low = dungeon.quest_for(7, 2, NOW)
    high = dungeon.quest_for(7, 30, NOW)
    assert high["zone"] >= low["zone"]
    assert high["coins"] > low["coins"]
    assert high["xp"] > low["xp"]
    if low["kind"] == "hunt":
        assert low["need"] <= 12


def test_quest_text_is_human():
    quest = dungeon.quest_for(1, 9, NOW)
    text = dungeon.quest_text(quest)
    assert text.startswith("убить")
    assert quest["zone_name"] in text


def test_page_has_quest_npc():
    for marker in ('id="questbtn"', 'id="questpanel"', 'id="qbody"',
                   "/api/dungeon/quest", "function questLoad(", "function questTake("):
        assert marker in DUNGEON_PAGE, marker
    # прогресс считается при убийстве мобов и босса
    assert "QUEST.kind === \"hunt\"" in DUNGEON_PAGE
    assert "QUEST.kind === \"boss\"" in DUNGEON_PAGE
