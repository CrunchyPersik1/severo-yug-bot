"""Мегаквест на карты должен быть выполнимым за неделю."""

from app import mega

QUEST = mega.QUESTS["drops"]


def test_cards_count_from_all_sources():
    sql = QUEST["sql"]
    assert "from drops" in sql
    assert "from cases" in sql and "opened" in sql
    assert "from gifts" in sql


def test_threshold_is_reachable_in_a_week():
    # VIP: 5 дропов в день = 35 за неделю, плюс кейсы из заданий и боссов
    assert min(QUEST["needs"]) <= 20
    assert max(QUEST["needs"]) <= 60


def test_title_matches_what_is_counted():
    assert "карты" in QUEST["title"].lower()


def test_weekly_quest_is_weekly():
    from datetime import datetime, timedelta, timezone

    monday = datetime(2026, 11, 16, 8, tzinfo=timezone.utc)
    assert mega.week_key(monday) == mega.week_key(monday + timedelta(days=6))
