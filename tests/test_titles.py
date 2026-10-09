"""Титулы игрока: очки вклада и пороги."""

from app import titles


def test_score_counts_everything():
    profile = {
        "unique_cards": 3,
        "total_cards": 4,
        "upgraded": 1,
        "wins": 2,
        "kills": 5,
        "casino_bets": 3,
        "market_deals": 1,
        "shop_buys": 1,
        "gifts_sent": 1,
        "invited": 1,
        "drops": 10,
        "promos": 1,
    }
    expected = (
        3 * 1 + 4 * 1 + 1 * 4 + 2 * 2 + 5 * 1 + 3 * 1 + 1 * 2 + 1 * 2
        + 1 * 2 + 1 * 5 + 10 * 1 + 1 * 3
    )
    assert titles.score(profile) == expected


def test_title_grows_with_score():
    assert titles.title_for({}) == "Новичок"
    assert titles.title_for({"unique_cards": 40}) == "Первоклашка"
    big = {
        "unique_cards": 50,
        "total_cards": 1000,
        "upgraded": 500,
        "wins": 1000,
        "kills": 2000,
        "casino_bets": 2000,
        "market_deals": 500,
        "shop_buys": 500,
        "gifts_sent": 200,
        "invited": 100,
        "drops": 1000,
        "promos": 50,
    }
    assert titles.title_for(big) == titles.TITLES[-1][1]


def test_progress_points():
    points, current, nxt = titles.progress({"drops": 30})
    assert points == 30
    assert current == 25
    assert nxt == 70
