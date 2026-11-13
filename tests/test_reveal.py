"""Скорость открытия: пять профилей и их влияние на страницы."""

import inspect

from app import reveal


def test_five_speeds_in_order():
    ids = [item["id"] for item in reveal.SPEEDS]
    assert ids == ["turbo", "fast", "normal", "slow", "turtle"]
    titles = [item["title"] for item in reveal.SPEEDS]
    assert titles[0] == "Супер быстрая"
    assert titles[-1] == "Черепаха"


def test_speeds_grow_monotonically():
    reels = [int(item["reel_ms"]) for item in reveal.SPEEDS]
    wheels = [int(item["wheel_ms"]) for item in reveal.SPEEDS]
    assert reels == sorted(reels) and len(set(reels)) == len(reels)
    assert wheels == sorted(wheels) and len(set(wheels)) == len(wheels)


def test_turtle_is_long_enough_for_suspense():
    assert reveal.reel_ms("turtle") >= 9000
    assert reveal.wheel_ms("turtle") >= 10000
    # и заметно дольше прежних 4.2 с
    assert reveal.reel_ms("slow") > 6000


def test_default_is_not_fast():
    assert reveal.DEFAULT == "slow"
    assert reveal.normalize("nope") == "slow"
    assert reveal.normalize(None) == "slow"
    assert reveal.normalize("turbo") == "turbo"


def test_batch_is_faster_but_not_instant():
    single = reveal.reel_ms("slow", 1)
    batch = reveal.reel_ms("slow", 5)
    assert batch < single
    assert batch >= reveal.MIN_BATCH_MS


def test_payload_for_settings():
    data = reveal.payload()
    assert len(data) == 5
    for item in data:
        assert item["id"] and item["title"] and item["reel_ms"]


def test_prefs_keep_and_validate_speed():
    from app.webapp import PREFS_DEFAULTS, _prefs_clean

    assert PREFS_DEFAULTS["speed"] == reveal.DEFAULT
    assert _prefs_clean({"speed": "turtle"})["speed"] == "turtle"
    assert _prefs_clean({"speed": "ракета"})["speed"] == reveal.DEFAULT


def test_api_exposes_speed_to_pages():
    from app import webapp

    case_source = inspect.getsource(webapp.api_case)
    assert '"speed":' in case_source and '"speeds":' in case_source
    payload_source = inspect.getsource(webapp._roulette_payload)
    assert "reveal_mod.normalize" in payload_source
    prefs_source = inspect.getsource(webapp.api_prefs)
    assert '"speeds": reveal_mod.payload()' in prefs_source


def test_pages_use_speed_and_creep():
    from app.games_page import CASE_PAGE, ROULETTE_PAGE

    for page in (CASE_PAGE, ROULETTE_PAGE):
        assert "SPEED_ID" in page
        assert "reelMs(" in page
        # вторая, медленная стадия «доползания»
        assert "creep" in page
    assert "wheelMs(" in ROULETTE_PAGE
    assert "spinTo(items[0].index || 0, msW)" in ROULETTE_PAGE


def test_settings_modal_has_speed_buttons():
    from app.webtheme import BOOTSTRAP

    assert "__speeds" in BOOTSTRAP
    assert "data-speed" in BOOTSTRAP
    assert "Скорость открытия" in BOOTSTRAP
