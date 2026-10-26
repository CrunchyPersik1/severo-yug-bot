"""Компактные полосы, крупное меню, скупка оружия."""

from app.webapp import DUNGEON_PAGE


def test_bars_are_compact_and_side_by_side():
    assert 'class="statbars"' in DUNGEON_PAGE
    assert 'class="statbar hp"' in DUNGEON_PAGE
    assert 'class="statbar xp"' in DUNGEON_PAGE
    # НР и опыт больше не отдельными блоками поверх экрана
    assert 'class="hpbar"' not in DUNGEON_PAGE
    assert 'class="xpbar"' not in DUNGEON_PAGE
    assert ".statbar{position:relative;flex:1;height:19px" in DUNGEON_PAGE


def test_bottom_menu_is_bigger():
    assert ".wmenu .wname{font-size:12px" in DUNGEON_PAGE
    assert ".wacts button{flex:1 1 0;min-width:0" in DUNGEON_PAGE
    # подписи короткие, чтобы влезали в три кнопки
    assert '("🛡 " + HERO_ARMOR.price + " Ю")' in DUNGEON_PAGE
    assert '("⬆ " + HERO_OFFER.price)' in DUNGEON_PAGE


def test_weapon_market_is_internal():
    # продажа прямо из сумки, без рынка Северо-Юга
    assert "function sellWeapon(" in DUNGEON_PAGE
    assert "function sellPrice(w)" in DUNGEON_PAGE
    assert 'data-sell="' in DUNGEON_PAGE
    assert 'href="/market"' not in DUNGEON_PAGE
    assert 'id="wfsell"' in DUNGEON_PAGE
    assert "Скупка оружия" in DUNGEON_PAGE


def test_safe_badge_under_bars():
    assert ".safebadge{position:fixed;left:50%;transform:translateX(-50%);top:80px;" in DUNGEON_PAGE
