"""Прототип боевой системы: страница, крючки, роут."""

import pathlib

from app.combat_page import COMBAT_PAGE

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_page_has_core_mechanics():
    for needle in (
        "playerAttack", "playerHeavy", "playerDash",
        "hitArc", "damageEnemy", "damagePlayer",
        "comboWindow", "iframes",
    ):
        assert needle in COMBAT_PAGE, needle


def test_three_hit_combo_and_stamina():
    assert "[14, 16, 26]" in COMBAT_PAGE      # урон по звеньям комбо
    assert "S.st -= 35" in COMBAT_PAGE         # замах
    assert "S.st -= 25" in COMBAT_PAGE         # рывок


def test_deterministic_step_hook_for_tests():
    assert "window.__combatStep" in COMBAT_PAGE
    assert "window.__combatState" in COMBAT_PAGE


def test_route_registered():
    webapp = (ROOT / "app" / "webapp.py").read_text(encoding="utf-8")
    assert '@router.get("/combat", response_class=HTMLResponse)' in webapp
    checker = (ROOT / "scripts" / "check_pages.py").read_text(encoding="utf-8")
    assert "app/combat_page.py" in checker
