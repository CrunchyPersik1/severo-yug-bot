"""Промокоды из базы и админ-команда promo."""

import pathlib

from app import admin_actions
from app.promo_db import PromoRepo

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_normalization_is_latin_only():
    assert PromoRepo.normalize(" Test-Code 1 ") == "testcode1"
    assert PromoRepo.normalize("северокод") == ""


def test_promo_command_registered():
    assert "promo" in admin_actions.COMMANDS
    assert "промо" in admin_actions.COMMANDS


def test_help_mentions_promo():
    assert "promo" in admin_actions.HELP


def test_until_parser():
    from datetime import timezone

    assert admin_actions._parse_until("-") is None
    moment = admin_actions._parse_until("18.11.2026 18:00")
    assert moment is not None and moment.tzinfo is not None
    assert moment.astimezone(timezone.utc).hour == 13  # 18:00 ЕКБ = 13:00 UTC


def test_schema_has_promo_tables():
    schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
    assert "create table if not exists promo_codes" in schema
    assert "create table if not exists promo_activations" in schema
    assert "uses_total" in schema and "expires_at" in schema


def test_redeem_checks_database_first():
    text = (ROOT / "app" / "promo.py").read_text(encoding="utf-8")
    body = text[text.index("async def redeem"):]
    assert body.index("PromoRepo(db).redeem") < body.index("PROMOS.get(code)")
