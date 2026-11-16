"""Акции не должны продавать топовое оружие за копейки."""

import random

from app import bundles, deals

RANKS = (0, 1, 3, 5, 7, 9)


def test_weapon_value_grows_with_rank():
    values = [bundles.weapon_value(f"sword_{rank}_4") for rank in RANKS]
    assert values == sorted(values)
    assert values[0] < values[-1] / 10  # топ реально дороже мусора


def test_deal_weapons_are_mid_tier():
    rng = random.Random(11)
    for _ in range(40):
        bundle, title, subtitle, emoji, color = deals._weapon(rng)
        rank = int(bundle["weapon"].split("_")[1])
        assert 1 <= rank <= 4, subtitle
        assert bundles.value(bundle) >= bundles.WEAPON_VALUES[1]


def test_top_weapon_is_never_cheap():
    # раньше ранг VIII стоил 23 000, теперь его оценка — сотни тысяч
    assert bundles.weapon_value("sword_7_4") > 200_000
    assert bundles.weapon_value("sword_8_0") > 300_000
