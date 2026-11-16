"""Мегаквест недели: ключ меняется раз в неделю, а не каждые сутки."""

from datetime import datetime, timedelta, timezone

from app import mega

MONDAY = datetime(2026, 11, 16, tzinfo=timezone.utc)  # понедельник, 07:00 UTC — ресет


def _moment(hours: float) -> datetime:
    return MONDAY + timedelta(hours=hours)


def test_key_is_stable_inside_the_week():
    keys = {mega.week_key(_moment(h)) for h in (7, 12, 23.5, 30, 71, 100, 160, 167)}
    assert len(keys) == 1, keys


def test_key_changes_only_at_monday_7_utc():
    before = mega.week_key(_moment(7) - timedelta(minutes=1))
    after = mega.week_key(_moment(7) + timedelta(minutes=1))
    assert before != after
    # и держится всю следующую неделю
    assert mega.week_key(_moment(7 + 24 * 6)) == after


def test_week_start_is_monday_7_utc():
    for hours in (0, 6, 12, 24 * 3, 24 * 6):
        start = mega.week_start(_moment(hours))
        assert start.weekday() == mega.RESET_WEEKDAY
        assert start.hour == mega.RESET_HOUR_UTC
        assert start <= _moment(hours)
