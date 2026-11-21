"""Подземелье: ближний бой с комбо, замахом и станом мобов."""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _page() -> str:
    src = (ROOT / "app" / "webapp.py").read_text(encoding="utf-8")
    start = src.index('DUNGEON_PAGE = r"""')
    return src[start:]


def test_combo_stages_and_timings():
    page = _page()
    assert "const COMBO_WINDOW = 0.55;" in page
    assert "Math.min(3, P.combo + 1)" in page
    assert "[0.85, 1.0, 1.6]" in page          # урон по звеньям
    assert "wind: stage === 3 ? 0.12 : 0.06" in page


def test_heavy_attack_via_hold():
    page = _page()
    assert "function heavyAttack()" in page
    assert "heavyAttack(); }, 320)" in page     # удержание кнопки
    assert "if (!held) attack();" in page       # короткий тап


def test_swing_is_applied_in_loop_with_cone():
    page = _page()
    assert "if (before < sw.wind && sw.t >= sw.wind) swingHit(sw);" in page
    assert "if (diff > sw.arc / 2) return;" in page


def test_mobs_stagger_and_have_ids():
    page = _page()
    assert 'id: "m" + (Math.random() * 1e9 | 0)' in page
    assert "m.stun = sw.heavy ? 0.4 : (sw.stage === 3 ? 0.28 : 0.14);" in page
    assert "if (m.stun > 0){" in page


def test_other_players_still_see_simple_animation():
    # состояние комбо не уходит в кооп: у чужих игроков старая простая анимация
    page = _page()
    for field in ("combo", "swing", "stun"):
        assert 'r.' + field not in page, field
