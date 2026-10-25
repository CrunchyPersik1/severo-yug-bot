
"""Юга-кликер: потолок и античит."""


def test_no_practical_cap():
    """Потолок снят: он мешал заданиям на накопление."""
    from app import yugi

    assert yugi.MAX_TOTAL >= 1e12, "потолок должен быть фактически отключён"
    total, balance = 0.0, 0.0
    for _ in range(200):
        total, balance = yugi.add_earned(total, balance, 1_000_000)
    assert total == 200_000_000
    assert total == balance


def test_huge_gain_credits_in_full():
    """Огромный разовый доход зачисляется целиком — потолка нет."""
    from app import yugi

    total, balance = yugi.add_earned(0.0, 0.0, 999_999_999)
    assert total == 999_999_999
    assert balance == 999_999_999


def test_human_tapping_is_not_punished():
    """Живой человек тапает ~10 раз в секунду — терять не должен ничего."""
    from datetime import datetime, timedelta, timezone

    from app import yugi

    now = datetime.now(timezone.utc)
    tokens = yugi.TAP_BURST
    window_at = now
    accepted_total = 0
    for step in range(200):          # 20 секунд по 10 тапов
        moment = now + timedelta(seconds=step * 0.1)
        available = yugi.tap_bucket(window_at, tokens, moment)
        accepted, tokens, _ = yugi.tap_take(available, 1)
        accepted_total += accepted
        window_at = moment
    assert accepted_total == 200, f"потеряли {200 - accepted_total} тапов"


def test_robot_flood_is_capped():
    """Робот, долбящий пачками по 300, упирается в норму."""
    from datetime import datetime, timedelta, timezone

    from app import yugi

    now = datetime.now(timezone.utc)
    tokens = yugi.TAP_BURST
    window_at = now
    accepted_total = 0
    for step in range(50):           # 5 секунд по 10 пачек
        moment = now + timedelta(seconds=step * 0.1)
        available = yugi.tap_bucket(window_at, tokens, moment)
        accepted, tokens, _ = yugi.tap_take(available, 300)
        accepted_total += accepted
        window_at = moment
    ceiling = int(yugi.TAP_BURST + 5 * yugi.MAX_TAPS_PER_SECOND) + 1
    assert accepted_total <= ceiling, f"пропустили {accepted_total} из 15000"
    assert accepted_total < 50 * 300 / 10


def test_empty_bucket_rejects_everything():
    from datetime import datetime, timezone

    from app import yugi

    now = datetime.now(timezone.utc)
    available = yugi.tap_bucket(now, 0, now)
    assert available == 0
    accepted, left, dropped = yugi.tap_take(available, 300)
    assert accepted == 0
    assert dropped == 300
    assert left == 0


def test_bucket_refills_over_time():
    from datetime import datetime, timedelta, timezone

    from app import yugi

    now = datetime.now(timezone.utc)
    available = yugi.tap_bucket(now, 0, now + timedelta(seconds=1))
    assert abs(available - yugi.MAX_TAPS_PER_SECOND) < 0.001
    # но выше запаса не наливает
    assert yugi.tap_bucket(now, 0, now + timedelta(hours=5)) == yugi.TAP_BURST
