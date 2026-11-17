"""Биржа: админ ставит курс сразу, а не ползёт к цели."""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_manual_price_updates_base_and_is_instant():
    src = (ROOT / "app" / "admin_actions.py").read_text(encoding="utf-8")
    start = src.index("async def act_stock(")
    end = src.index("async def act_theme(")
    block = src[start:end]
    # цена, база и сброс пампов — одним апдейтом, без «цели»
    assert "set price = $2" in block
    assert "base_price = $2" in block
    assert "target_price = null" in block
    assert "pump_phase = null" in block
    assert "update stocks set target_price = $2" not in block


def test_corridor_still_guards_auto_targets():
    from app.stocks import CEIL_MULT, FLOOR_MULT, clamp_target

    assert FLOOR_MULT == 0.40
    assert CEIL_MULT == 2.20
    # цель ниже пола/выше потолка обрезается — это для автоцелей,
    # ручная установка идёт через base_price
    assert clamp_target(10, 1000) == 400
    assert clamp_target(99_999, 1000) == 2200
