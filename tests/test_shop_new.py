"""Новый магазин: акции, паки, ежедневка, мегаквест и кристаллы с мобов."""

import random
from datetime import date, datetime, timezone

import pytest

from app import bundles, daily, deals, gems, mega, packs
from app.shop import TEACHERS_PER_DAY, catalog, teachers_of_day


# --------------------------------------------------------------------------- #
# Акции
# --------------------------------------------------------------------------- #


def test_six_deals_always_four_shared_two_personal():
    period = deals.period_of()
    items = deals.all_for(12345, period)
    assert len(items) == 6
    assert sum(1 for d in items if not d["personal"]) == 4
    assert sum(1 for d in items if d["personal"]) == 2


def test_shared_deals_are_the_same_for_everyone():
    period = deals.period_of()
    first = [d["id"] for d in deals.shared(period)]
    second = [d["id"] for d in deals.shared(period)]
    assert first == second
    # личные — разные у разных игроков
    a = [d["title"] for d in deals.personal(period, 1)]
    b = [d["title"] for d in deals.personal(period, 2)]
    assert a != b


def test_deals_change_next_period():
    period = deals.period_of()
    assert deals.period_of() == period
    early = [d["title"] for d in deals.all_for(1, period)]
    later = [d["title"] for d in deals.all_for(1, period + 1)]
    assert early != later


def test_deal_ids_are_unique_and_stable():
    period = deals.period_of()
    ids = [d["id"] for d in deals.all_for(7, period)]
    assert len(set(ids)) == 6
    assert ids == [d["id"] for d in deals.all_for(7, period)]


def test_every_deal_has_price_and_discount():
    for deal in deals.all_for(99, deals.period_of()):
        assert deal["price"] > 0
        assert deal["old_price"] > deal["price"]
        assert 5 <= deal["discount"] <= 85
        assert deal["currency"] in (deals.CURRENCY_POINTS, deals.CURRENCY_GEMS)
        assert deal["contents"]
        assert deal["emoji"]


def test_gems_are_never_sold_for_gems():
    for period in range(40, 60):
        for deal in deals.all_for(5, period):
            if deal["bundle"].get("gems"):
                assert deal["currency"] == deals.CURRENCY_POINTS


def test_deal_content_is_worth_more_than_price():
    for deal in deals.all_for(3, deals.period_of()):
        real = bundles.value(deal["bundle"])
        paid = (
            deal["price"] * bundles.GEM_RATE
            if deal["currency"] == deals.CURRENCY_GEMS
            else deal["price"]
        )
        assert real >= paid, deal["title"]


def test_find_returns_only_current_deals():
    period = deals.period_of()
    deal = deals.all_for(11, period)[0]
    assert deals.find(11, period, deal["id"]) is not None
    assert deals.find(11, period, "p0-s0") is None


def test_period_is_four_days():
    assert deals.PERIOD_DAYS == 4
    moment = datetime(2026, 5, 1, 12, tzinfo=timezone.utc)
    assert deals.period_end(moment) > moment
    assert deals.period_of(moment) != deals.period_of(
        moment.replace(day=6)
    )


# --------------------------------------------------------------------------- #
# Топ-паки
# --------------------------------------------------------------------------- #


def test_packs_are_one_to_three_and_unique():
    for period in range(60, 80):
        picked = packs.roulette(period)
        assert 1 <= len(picked) <= packs.MAX_PER_PERIOD
        assert len({p["id"] for p in picked}) == len(picked)


def test_packs_cost_only_gems():
    for period in range(60, 80):
        for pack in packs.roulette(period):
            assert pack["currency"] == "gems"
            assert pack["price"] > 0
            assert pack["old_price"] > pack["price"]


def test_pack_examples_from_spec():
    mega_pack = packs.PACK_BY_ID["mega"]
    assert mega_pack["price"] == 350
    assert mega_pack["bundle"]["cases_g"] == 10
    assert mega_pack["bundle"]["vip_days"] == 14
    assert "valeriya" in mega_pack["bundle"]["cards"]
    triple = packs.PACK_BY_ID["triple"]
    assert triple["price"] == 150
    assert len(triple["bundle"]["cards"]) == 3


def test_find_pack_only_in_current_rotation():
    period = deals.period_of()
    first = packs.roulette(period)[0]
    assert packs.find(period, first["id"]) is not None
    assert packs.find(period, "no-such-pack") is None


# --------------------------------------------------------------------------- #
# Ежедневная награда
# --------------------------------------------------------------------------- #


def test_daily_weights_sum_to_one_hundred():
    assert abs(sum(daily.WEIGHTS.values()) - 100.0) < 1e-9


def test_daily_can_give_every_tier():
    rng = random.Random(42)
    seen = set()
    for _ in range(60_000):
        seen.add(daily.roll(rng)["tier"])
    assert seen == set(daily.WEIGHTS)


def test_daily_jackpot_is_rare():
    rng = random.Random(7)
    jackpots = sum(1 for _ in range(50_000) if daily.roll(rng)["tier"] == daily.TIER_JACKPOT)
    assert 100 < jackpots < 500, jackpots


def test_daily_streak_bonus_after_week():
    assert daily.streak_multiplier(1) == 1.0
    assert daily.streak_multiplier(6) == 1.0
    assert daily.streak_multiplier(7) == 1.5


def test_daily_multiplier_scales_numbers_only():
    prize = {"tier": daily.TIER_POINTS, "title": "100 очков", "bundle": {"points": 100}}
    scaled = daily.apply_multiplier(prize, 1.5)
    assert scaled["bundle"]["points"] == 150
    cases = {"tier": daily.TIER_CASE, "title": "кейс", "bundle": {"cases_g": 1}}
    assert daily.apply_multiplier(cases, 1.5)["bundle"]["cases_g"] == 1
    jackpot = {"tier": daily.TIER_JACKPOT, "title": "джекпот", "bundle": {"gems": 15}}
    assert daily.apply_multiplier(jackpot, 1.5)["bundle"]["gems"] == 15


# --------------------------------------------------------------------------- #
# Кристаллы с мобов
# --------------------------------------------------------------------------- #


def test_gem_chance_grows_with_zone_but_stays_small():
    first = gems.chance(0)
    last = gems.chance(9)
    assert first < last
    assert 0.0005 <= first and last <= 0.005


def test_gem_amount_range_by_zone():
    assert gems.amount_range(0)[0] >= 2
    assert gems.amount_range(9)[1] == gems.AMOUNT_MAX
    low, high = gems.amount_range(4)
    assert low <= high


def test_gem_roll_is_rare():
    rng = random.Random(3)
    drops = sum(1 for _ in range(20_000) if gems.roll(9, rng) > 0)
    # 0.4% от 20 000 — около 80
    assert 0 < drops < 250, drops


def test_gem_cooldown_is_ten_seconds():
    assert gems.COOLDOWN_SECONDS == 10


# --------------------------------------------------------------------------- #
# Мегаквест
# --------------------------------------------------------------------------- #


def test_ten_mega_quests():
    assert len(mega.QUESTS) == 10
    for key, quest in mega.QUESTS.items():
        assert quest["title"]
        assert "$1" in quest["sql"] and "$2" in quest["sql"]
        assert min(quest["needs"]) > 0


def test_week_starts_monday_at_seven_utc():
    moment = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)  # суббота
    start = mega.week_start(moment)
    assert start.weekday() == 0
    assert start.hour == 7
    assert mega.week_key(moment) == mega.week_key(start)


def test_mega_quest_is_deterministic_per_week():
    moment = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
    first = mega.quest(moment)
    assert first == mega.quest(moment)
    assert first["key"] in mega.QUESTS
    assert first["need"] in mega.QUESTS[first["key"]]["needs"]


def test_mega_reward_is_big():
    for week in range(40):
        moment = datetime(2026, 1, 5, 12, tzinfo=timezone.utc)
        moment = moment.replace(day=1 + (week % 28))
        reward = mega.quest(moment)["reward"]
        # Крупная награда: не меньше самостоятельного пака кейсов.
        assert bundles.value(reward) >= 40_000


# --------------------------------------------------------------------------- #
# Наборы наград
# --------------------------------------------------------------------------- #


def test_bundle_value_and_text():
    bundle = bundles.make(points=1000, cases_g=2, cards=["oleg"])
    assert bundles.value(bundle) > 10_000
    assert any("очков" in part for part in bundles.labels(bundle))


def test_bundle_rejects_unknown_keys():
    with pytest.raises(ValueError):
        bundles.make(rockets=3)


def test_gem_rate_matches_spec():
    # 180 кристаллов ≈ 10 млн очков
    assert abs(bundles.GEM_RATE * 180 - 10_000_000) < 200_000


# --------------------------------------------------------------------------- #
# Учителя дня
# --------------------------------------------------------------------------- #


def test_teachers_rotate_daily_and_are_six():
    today = teachers_of_day(date(2026, 11, 14))
    tomorrow = teachers_of_day(date(2026, 11, 15))
    assert len(today) == TEACHERS_PER_DAY
    assert len({c.card_id for c in today}) == TEACHERS_PER_DAY
    assert [c.card_id for c in today] == [c.card_id for c in teachers_of_day(date(2026, 11, 14))]
    assert [c.card_id for c in today] != [c.card_id for c in tomorrow]


def test_catalog_has_only_todays_teachers():
    day = date(2026, 11, 14)
    skus = {entry.sku for entry in catalog(day)}
    allowed = {f"card:{card.card_id}" for card in teachers_of_day(day)}
    teacher_skus = {sku for sku in skus if sku.startswith("card:")}
    assert teacher_skus <= allowed
    assert len(teacher_skus) <= TEACHERS_PER_DAY
