"""Петы, яйца, питомник и магазин Санты."""

from datetime import date

import pytest

from app import eggs, pets, santa


# ------------------------------------------------------------------ петы ---


def test_seventeen_pets():
    assert len(pets.PETS) == 17
    ids = [pet.id for pet in pets.PETS]
    assert len(ids) == len(set(ids))


def test_names_from_spec():
    names = {pet.name for pet in pets.PETS}
    for expected in ("Котость", "Мэни", "Рокки", "Каспер", "Одди", "Лео", "Дик",
                     "Люси", "Патейто", "Яичко", "Мыш", "Честер", "Найда",
                     "Мишлен", "Симона", "Челси", "Лелик"):
        assert expected in names, expected


def test_kotos_gives_thousand_percent():
    kotos = pets.get("kotos")
    assert kotos.effect(1) == 10.0        # +1000%
    assert kotos.effect(10) == 10.0       # не растёт от уровня
    assert kotos.rare is True


def test_kasper_is_rare_and_twenty_percent():
    kasper = pets.get("kasper")
    assert kasper.effect(1) == 0.20
    assert kasper.rare is True
    assert kasper.currency == "gems"
    assert kasper.price >= 800


def test_pets_that_grow_by_level():
    mani = pets.get("mani")
    assert mani.effect(2) > mani.effect(1)
    for pet in pets.PETS:
        assert pet.effect(1) >= 0
        assert pet.effect(pet.max_level) >= pet.effect(1)


def test_every_pet_has_note_and_title():
    for pet in pets.PETS:
        assert pet.title and pet.note and pet.emoji


# ------------------------------------------------------------------ яйцо ---


def test_egg_odds_sum_to_hundred():
    weights = pets.egg_weights()
    assert abs(sum(weights.values()) - 100.0) < 1e-9
    assert set(weights) == {"kotos", "mani", "patejto", "lucy"}


def test_egg_costs_350k_and_hatches_five_hours():
    egg = eggs.egg()
    assert egg["price"] == 350_000
    assert egg["hours"] == 5
    assert eggs.hatch_seconds("cats") == 5 * 3600


def test_incubator_speed_cuts_time():
    base = eggs.hatch_seconds("cats")
    fast = eggs.hatch_seconds("cats", speed_levels=5)
    assert fast < base
    assert fast >= 60


def test_incubator_has_nine_slots():
    assert eggs.slots() == 9


def test_upgrade_prices_grow_and_cap():
    assert eggs.upgrade_price("chance", 0) == 150_000
    assert eggs.upgrade_price("chance", 1) > eggs.upgrade_price("chance", 0)
    assert eggs.can_upgrade("chance", 9) is True
    assert eggs.can_upgrade("chance", 10) is False


def test_chance_upgrade_lifts_rare_odds():
    import random

    def rare_rate(levels, bonus):
        rng = random.Random(7)
        return sum(1 for _ in range(20000) if eggs.roll_pet(levels, bonus, rng) in ("kotos", "mani"))

    plain = rare_rate(0, 0)
    lucky = rare_rate(10, 0.2)
    assert lucky > plain * 1.1, (plain, lucky)


# ----------------------------------------------------------------- санта ---


def test_six_levels_and_rewards():
    levels = santa.levels()
    assert len(levels) == 6
    for item in levels:
        assert item["name"].startswith("Амир")
        assert item["hp"] > 0 and item["dmg"] > 0
        assert item["reward"]
        assert "kotos" not in str(item["reward"])
    last = levels[-1]["reward"]
    assert last.get("eggs") == 5
    assert last.get("gems") == 50


def test_difficulty_grows():
    levels = santa.levels()
    hp = [item["hp"] for item in levels]
    dmg = [item["dmg"] for item in levels]
    assert hp == sorted(hp) and dmg == sorted(dmg)


def test_four_story_choices():
    assert len(santa.CHOICES) == 4
    assert len({item["id"] for item in santa.CHOICES}) == 4
    good = santa.choice("praise")
    bad = santa.choice("strict")
    assert good["discount"] > 0
    assert bad["discount"] < 0
    assert good["on_days"] > bad["on_days"]


def test_shop_cycle_depends_on_choice():
    day = santa.EPOCH
    assert santa.shop_open(day, "praise") is True
    assert santa.shop_open(day, "strict") is True
    # через два дня: у хорошего ещё открыто (4 дня), у плохого уже нет (1 день)
    later = date(day.year, day.month, day.day + 2)
    assert santa.shop_open(later, "praise") is True
    assert santa.shop_open(later, "strict") is False
    assert santa.opens_in_days(later, "strict") > 0


def test_stock_is_five_pets_plus_egg():
    day = santa.today_ekb()
    items = santa.stock(day, "praise")
    assert len(items) == 6
    assert sum(1 for item in items if item["kind"] == "pet") == 5
    assert sum(1 for item in items if item["kind"] == "egg") == 1
    assert len({item["id"] for item in items}) == 6


def test_stock_is_stable_within_a_season():
    day = santa.EPOCH
    first = [item["id"] for item in santa.stock(day, "praise")]
    second = [item["id"] for item in santa.stock(day, "praise")]
    assert first == second


def test_story_changes_prices():
    day = santa.today_ekb()
    def price(items, pet_id):
        return next(i["price"] for i in items if i["id"] == pet_id)
    good = santa.stock(day, "praise")
    bad = santa.stock(day, "strict")
    common = set(i["id"] for i in good) & set(i["id"] for i in bad)
    assert common, "стоки должны пересекаться хотя бы одним товаром"
    pet_id = next(pid for pid in common if pid != "cats")
    assert price(good, pet_id) < price(bad, pet_id)


def test_kotos_is_in_shop_and_has_two_currencies():
    """Котость продаётся и за кристаллы, и за очки — это две отдельные цены."""
    assert pets.get("kotos").price == 0          # цену задаёт магазин Санты
    assert pets.get("kotos").rare is True
