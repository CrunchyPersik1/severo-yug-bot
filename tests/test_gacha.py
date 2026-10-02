import random
from collections import Counter
from datetime import datetime, timedelta, timezone

from app.cards import CARDS_BY_RARITY, RARITIES
from app.gacha import RESET_HOUR_UTC, day_key, next_reset, roll_card, roll_rarity


def test_day_key_resets_at_0700_utc():
    before = datetime(2026, 5, 1, 6, 59, tzinfo=timezone.utc)
    after = datetime(2026, 5, 1, 7, 0, tzinfo=timezone.utc)
    assert day_key(before) != day_key(after)
    assert day_key(after) == datetime(2026, 5, 1, tzinfo=timezone.utc).date()


def test_day_key_is_ekb_calendar_day():
    # 12:00 ЕКБ == 07:00 UTC
    moment = datetime(2026, 5, 1, 7, 30, tzinfo=timezone.utc)
    assert day_key(moment) == datetime(2026, 5, 1).date()


def test_next_reset_is_in_the_future():
    moment = datetime(2026, 5, 1, 20, 0, tzinfo=timezone.utc)
    nxt = next_reset(moment)
    assert nxt == datetime(2026, 5, 2, RESET_HOUR_UTC, tzinfo=timezone.utc)
    assert next_reset(datetime(2026, 5, 1, 3, 0, tzinfo=timezone.utc)) == datetime(
        2026, 5, 1, RESET_HOUR_UTC, tzinfo=timezone.utc
    )


def test_roll_card_stays_inside_rarity():
    rng = random.Random(42)
    for _ in range(300):
        card = roll_card(rng)
        assert card in CARDS_BY_RARITY[card.rarity]


def test_secrets_are_rare_but_possible():
    rng = random.Random(7)
    rolls = Counter(roll_rarity(rng) for _ in range(200_000))
    total = sum(rolls.values())
    secret_share = (rolls["secret"] + rolls["ultra"]) / total
    assert 0.006 < secret_share < 0.014
    for key, rarity in RARITIES.items():
        assert abs(rolls[key] / total - rarity.weight) < 0.01, key


def test_rarest_card_appears_eventually():
    rng = random.Random(1234)
    seen = {roll_card(rng).card_id for _ in range(400_000)}
    assert "valeriya" in seen
    assert "amiliya_secret" in seen
