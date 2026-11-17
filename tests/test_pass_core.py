"""Северо-Пасс: сезоны, уровни, квесты и награды (основа)."""

from datetime import date, datetime, timedelta, timezone

from app import bundles, pass_config, pass_quests, pass_rewards


def test_season_is_calendar_month():
    moment = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
    assert pass_config.season_key(moment) == "2026-11"
    assert pass_config.season_start(moment).day == 1
    # декабрь — следующий сезон
    assert pass_config.season_key(moment + timedelta(days=20)) == "2026-12"


def test_level_costs_match_spec():
    assert pass_config.LEVEL_COST[1] == 50
    assert pass_config.LEVEL_COST[2] == 150
    assert pass_config.LEVEL_COST[3] == 350
    assert pass_config.LEVEL_COST[10] == 350
    assert pass_config.LEVEL_COST[11] == 950
    assert pass_config.LEVEL_COST[40] == 950
    assert pass_config.LEVEL_COST[41] == 1250
    assert pass_config.LEVEL_COST[50] == 1250
    assert pass_config.TOTAL_XP == 44_000


def test_level_for_accumulates():
    assert pass_config.level_for(0) == 0
    assert pass_config.level_for(49) == 0
    assert pass_config.level_for(50) == 1
    assert pass_config.level_for(200) == 2
    assert pass_config.level_for(pass_config.TOTAL_XP) == 50


def test_bonus_steps_after_fifty():
    base = pass_config.TOTAL_XP
    assert pass_config.bonus_steps(base) == 0
    assert pass_config.bonus_steps(base + pass_config.BONUS_STEP) == 1
    assert pass_config.bonus_steps(base + pass_config.BONUS_STEP * 3 + 5) == 3


def test_daily_quests_layout_and_xp():
    quests = pass_quests.daily("2026-11", date(2026, 11, 17))
    tiers = [q["tier"] for q in quests if not q["plus"]]
    assert tiers.count("light") == 3
    assert tiers.count("medium") == 3
    assert tiers.count("hard") == 1
    assert pass_quests.day_xp(quests) == 3100
    plus = [q for q in quests if q["plus"]]
    assert len(plus) == 2
    assert pass_quests.day_xp(quests, with_plus=True) == 4300


def test_quests_are_deterministic_per_day():
    a = pass_quests.daily("2026-11", date(2026, 11, 17))
    b = pass_quests.daily("2026-11", date(2026, 11, 17))
    assert [q["key"] for q in a] == [q["key"] for q in b]


def test_free_track_has_no_cards_or_styles():
    for row in pass_rewards.levels("2026-11"):
        free = row["free"]
        assert not free["cards"], row["level"]
        assert not free["shares"], row["level"]
        assert not free["vip_days"], row["level"]


def test_premium_track_only_on_windows():
    for row in pass_rewards.levels("2026-11"):
        if 10 < row["level"] < 41:
            assert row["premium"] is None, row["level"]
        else:
            assert row["premium"] is not None, row["level"]


def test_bonus_choice_has_paid_option():
    first, second = pass_rewards.bonus_choices("2026-11", 1)
    assert first["gems"] == 0
    assert 19 <= second["gems"] <= 79
    assert bundles.value(second["bundle"]) > bundles.value(first["bundle"])


def test_theme_season_one():
    assert pass_config.theme()["name"] == "Академия Северо-Южных"
    assert pass_config.theme()["title"] == "Лучший из лучших"
