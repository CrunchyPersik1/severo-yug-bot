"""Кейс «Ультра» продаётся в магазине, открывается на странице кейсов."""

import io


def _pay():
    from app import cases, shop

    return cases, shop


def test_shop_sells_ultra_case():
    cases, shop = _pay()
    skus = {entry.sku: entry for entry in shop.catalog()}
    assert shop.CASE_ULTRA_SKU in skus
    entry = skus[shop.CASE_ULTRA_SKU]
    assert entry.kind == "case_ultra"
    assert entry.price == cases.ULTRA_CASE_PRICE == 15_000
    assert "Ультра" in entry.title


def test_cases_page_has_tiles_and_roulette():
    from app.games_page import CASE_PAGE

    # три плитки кейсов и рулетка рядом
    assert 'data-k="g"' in CASE_PAGE
    assert 'data-k="d"' in CASE_PAGE
    assert 'data-k="u"' in CASE_PAGE
    assert 'href="/roulette_app"' in CASE_PAGE
    # покупки на странице кейсов больше нет
    assert "ultraOpen" not in CASE_PAGE
    assert "Открыть за 15 000" not in CASE_PAGE


def test_open_ultra_returns_results():
    from app import webapp

    source = open("app/webapp.py", encoding="utf-8").read()
    assert '"results": results' in source
    assert 'error_text = "Кейсов «Ультра» нет"' in source
    # отдельной покупки-с-открытием больше нет
    assert '@router.post("/api/case/ultra")' not in source
    # магазин знает новую вкладку
    assert '["case_ultra","🌈 Кейс Ультра"]' in source
    assert webapp  # модуль импортируется


def test_shop_page_css_restored():
    """Патч биржи когда-то затёр стили магазина — держим проверку."""
    from app.webapp import PAGE

    assert ".tabs{" in PAGE
    assert ".wallet{" in PAGE
    assert "--ex-bg" not in PAGE
