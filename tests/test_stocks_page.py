"""Страница биржи: все элементы на месте, палитра одна."""

from app.webapp import STOCKS_PAGE

# id, которые страница дёргает из JS — пропадёт любой, и биржа молча умрёт
REQUIRED_IDS = (
    "nm", "sub", "pr", "ch",
    "stBuy", "stSell", "stShares", "stPnl",
    "pf", "pfSpent", "pfValue", "pfPnl", "pfSub",
    "cv", "note", "stepBar", "buyBtn", "sellBtn", "rows", "toast",
)


def test_all_js_ids_exist():
    for name in REQUIRED_IDS:
        assert 'id="%s"' % name in STOCKS_PAGE, name


def test_one_palette():
    # старая вёрстка тащила две палитры: тёплую и терминал
    assert "#26a69a" not in STOCKS_PAGE
    assert "#131722" not in STOCKS_PAGE
    assert "#ef5350" not in STOCKS_PAGE
    # свечи в цвет бота
    assert 'upColor: "#9dc941"' in STOCKS_PAGE
    assert 'downColor: "#e0407a"' in STOCKS_PAGE


def test_trade_bar_and_header():
    assert 'class="dock"' in STOCKS_PAGE
    assert 'id="stepBar"' in STOCKS_PAGE
    assert 'href="/hub"' in STOCKS_PAGE
    assert "БИРЖА" in STOCKS_PAGE
    # шапку от темы бота прячем, иначе их две
    assert "#__back{display:none!important}" in STOCKS_PAGE


def test_logic_untouched():
    for needle in ("function candles(", "function draw(", "async function trade(",
                   "async function load(", "/api/stocks/", "setInterval("):
        assert needle in STOCKS_PAGE, needle
