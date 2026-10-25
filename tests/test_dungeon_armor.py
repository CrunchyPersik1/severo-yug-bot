"""Тесты: броня за Юги, Юги за босса, лидерборд."""

from app import dungeon


def test_armor_price_grows_with_level_and_resets():
    assert dungeon.armor_price(0, 0) == dungeon.ARMOR_BASE
    assert dungeon.armor_price(1, 0) > dungeon.armor_price(0, 0)
    assert dungeon.armor_price(0, 2) > dungeon.armor_price(0, 0)
    assert dungeon.armor_price(dungeon.ARMOR_MAX, 0) is None
    assert dungeon.armor_price(dungeon.ARMOR_MAX + 5, 0) is None


def test_armor_discount_caps():
    assert dungeon.armor_discount(0) == 0.0
    assert dungeon.armor_discount(1) == 0.04
    assert dungeon.armor_discount(5) == 0.2
    assert dungeon.armor_discount(99) == round(dungeon.ARMOR_MAX * dungeon.ARMOR_STEP, 4)
    assert dungeon.armor_discount("мусор") == 0.0


def test_armor_offer_shape():
    offer = dungeon.armor_offer(0, 0)
    assert offer["price"] == dungeon.ARMOR_BASE
    assert offer["next"] == 1
    assert offer["next_discount"] > offer["discount"]
    assert dungeon.armor_offer(dungeon.ARMOR_MAX, 0) is None


def test_boss_yugi_grows_with_zone():
    assert dungeon.boss_yugi(0) >= 5
    assert dungeon.boss_yugi(9) > dungeon.boss_yugi(0)


def test_boss_reward_includes_yugi():
    reward = dungeon.boss_reward(0, 1)
    assert reward["yugi"] == dungeon.boss_yugi(0)
    assert reward["coins"] >= 1 and reward["kills"] == 1
