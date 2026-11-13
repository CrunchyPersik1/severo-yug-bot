"""Прокрут приза: одна быстрая анимация с плавным торможением (как в CS)."""

import inspect

from app import reveal


def test_durations_are_short_enough():
    assert reveal.REEL_MS <= 5000
    assert reveal.WHEEL_MS <= 6000
    assert reveal.HOLD_MS <= 600


def test_curve_starts_fast_and_ends_slow():
    # cubic-bezier(x1,y1,x2,y2): y1 высокий — резкий старт, x2/y2 — мягкий финиш
    nums = [float(part) for part in reveal.CURVE.replace("cubic-bezier(", "").replace(")", "").split(",")]
    assert len(nums) == 4
    x1, y1, x2, y2 = nums
    assert y1 > 0.6, "лента должна сразу лететь"
    assert x2 > 0.05 and y2 >= 0.95, "и плавно тормозить в конце"


def test_payload_shape():
    data = reveal.payload()
    assert data["reel_ms"] == reveal.REEL_MS
    assert data["wheel_ms"] == reveal.WHEEL_MS
    assert data["hold_ms"] == reveal.HOLD_MS
    assert data["curve"] == reveal.CURVE


def test_no_stages_or_slips_left():
    source = inspect.getsource(reveal)
    for old in ("STAGE_TILES", "SLIP_TILES", "SLIP_CHANCE", "stage_ms"):
        assert old not in source, old


def test_api_sends_single_spin_config():
    from app import webapp

    assert '"spin": reveal_mod.payload()' in inspect.getsource(webapp.api_case)
    assert '"spin": reveal_mod.payload()' in inspect.getsource(webapp._roulette_payload)


def test_pages_have_one_continuous_animation():
    from app.games_page import CASE_PAGE, ROULETTE_PAGE

    for page in (CASE_PAGE, ROULETTE_PAGE):
        assert "reelMs()" in page
        assert "spinCurve()" in page
        for old in ("spinPlan", "slip", "stage_tiles", "SPEED", "plan.ms", "reelMs(count)"):
            assert old not in page, old
    # одна transition на весь прокрут, без цепочки таймеров
    assert page.count("setTimeout") >= 1


def test_case_reel_lands_exactly_once():
    from app.games_page import CASE_PAGE

    # ровно один вызов перехода внутри spinOne
    block = CASE_PAGE.split("function spinOne(item, ms){")[1].split("function sync")[0]
    assert block.count('style.transition = "transform') == 1
    assert block.count("setTimeout") == 1
