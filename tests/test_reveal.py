"""Открытие приза: 15 секунд, три стадии и «проскок» на соседний тайл."""

import inspect

from app import reveal


def test_spin_is_at_least_fifteen_seconds():
    assert reveal.SPIN_MS == 15_000
    assert reveal.total_ms() >= 15_000


def test_three_stages_add_up_to_the_whole_time():
    first, second, third = reveal.stage_ms()
    assert first + second + third == reveal.SPIN_MS
    assert first > second > third, "сначала быстро, потом медленнее, потом совсем медленно"


def test_stage_shares():
    assert abs(sum(reveal.STAGE_SHARE) - 1.0) < 1e-9
    assert reveal.STAGE_SHARE[0] > reveal.STAGE_SHARE[1] > reveal.STAGE_SHARE[2]


def test_stage_ms_never_shorter_than_minimum():
    first, second, third = reveal.stage_ms(1000)
    assert first + second + third == reveal.SPIN_MS


def test_slip_chance_is_fifteen_percent():
    assert reveal.slip_chance() == 0.15


def test_usual_end_barely_moves():
    """Обычно лента почти не сдвигается после «остановки»."""
    usual = reveal.STAGE_TILES[-1]
    slip = reveal.SLIP_TILES[-1]
    assert usual < 0.6
    assert slip > 1.0
    assert slip > usual


def test_payload_for_pages():
    data = reveal.payload()
    assert data["spin_ms"] == reveal.SPIN_MS
    assert len(data["spin_stages"]) == 3
    assert sum(data["spin_stages"]) == reveal.SPIN_MS
    assert data["slip_chance"] == reveal.SLIP_CHANCE
    assert len(data["stage_tiles"]) == 3 and len(data["slip_tiles"]) == 3


def test_api_sends_spin_config():
    from app import webapp

    assert '"spin": reveal_mod.payload()' in inspect.getsource(webapp.api_case)
    assert '"spin": reveal_mod.payload()' in inspect.getsource(webapp._roulette_payload)


def test_no_speed_profiles_left():
    from app import webapp
    from app.webapp import PREFS_DEFAULTS

    assert "speed" not in PREFS_DEFAULTS
    assert "speed" not in inspect.getsource(webapp.api_prefs)


def test_pages_use_stages_and_slip():
    from app.games_page import CASE_PAGE, ROULETTE_PAGE

    for page in (CASE_PAGE, ROULETTE_PAGE):
        assert "spinPlan" in page
        assert "slip" in page
        assert "spin_ms" in page
        for old in ("SPEEDS", "SPEED_ID", "reelMs(", "wheelMs("):
            assert old not in page, old
    assert "spinTo(items[0].index || 0, plan)" in ROULETTE_PAGE


def test_settings_have_no_speed_row():
    from app.webtheme import BOOTSTRAP

    assert "__speeds" not in BOOTSTRAP
    assert "Скорость открытия" not in BOOTSTRAP
