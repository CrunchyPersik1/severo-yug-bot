"""Покупка Пасс++ и награды премиум-дорожки."""

import pathlib

from app.pass_page import PASS_PAGE

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_direct_premium_purchase_sends_premium_kind():
    # раньше кнопка «Северо-Пасс++» слала kind="upgrade" и сервер отвечал
    # «Сначала купи Северо-Пасс+»
    assert 'kind: p.plus ? "upgrade" : "premium"' in PASS_PAGE
    assert 'data-buy' in PASS_PAGE


def test_premium_rewards_use_server_track_name():
    assert '"premium", row.level' in PASS_PAGE
    assert '"prem", row.level' not in PASS_PAGE


def test_shortfall_message_explains_cheaper_route():
    src = (ROOT / "app" / "pass_repo.py").read_text(encoding="utf-8")
    assert "Не хватает " in src
    assert "потом апгрейд за" in src
    assert "PRICE_PLUS_GEMS + pass_config.PRICE_UPGRADE_GEMS" in src


def test_gifts_after_payment_cannot_break_purchase():
    src = (ROOT / "app" / "pass_repo.py").read_text(encoding="utf-8")
    assert "не выдался подарок за сп++" in src
