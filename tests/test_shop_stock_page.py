"""Сток: вызовы из страницы магазина."""

import re

from app.webapp import PAGE


def test_stock_loaded_on_page_load():
    # раньше stockLoad() не вызывался вообще: висело «загружаю» и таймер 5:00
    load_fn = PAGE.split("async function load(){", 1)[1].split("\n}", 1)[0]
    assert "stockLoad()" in load_fn


def test_stock_uses_get_and_wires_buttons():
    assert 'fetch("/api/shop/stock", {headers})' in PAGE
    assert "stockReroll" in PAGE
    assert 'id="stkReroll"' in PAGE
    # две цены на карту
    assert 'data-cur="gems"' in PAGE and 'data-cur="points"' in PAGE
