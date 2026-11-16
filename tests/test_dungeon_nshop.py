"""Покупка у Насибуллина: тело запроса, а не опции fetch."""

from app.webapp import DUNGEON_PAGE


def test_buy_sends_body_not_fetch_options():
    # coopApi(path, body) — второй аргумент это JSON-тело.
    # Раньше сюда передавали {method, body}, сервер не видел id и отвечал
    # «Такого оружия сегодня нет» — поэтому ничего не покупалось.
    assert 'coopApi("/api/dungeon/shop/buy", {id: id})' in DUNGEON_PAGE
    assert 'coopApi("/api/dungeon/shop/buy", {method' not in DUNGEON_PAGE


def test_shop_helpers_exist():
    assert "async function openShop()" in DUNGEON_PAGE
    assert "async function buyWeapon(id)" in DUNGEON_PAGE
    assert 'id="nslist"' in DUNGEON_PAGE
    assert 'id="nshopbtn"' in DUNGEON_PAGE
