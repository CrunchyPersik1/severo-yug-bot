"""Оффлайн-точка на стыке локаций и полное состояние кликера."""

from app.webapp import DUNGEON_PAGE, YUGI_PAGE


def test_offline_corner_moved_to_junction():
    source = DUNGEON_PAGE
    assert "const junction = WORLD.h - ZONE_H;" in source
    # точка выше низа карты: HUD её больше не закрывает
    assert "junction - 46" in source
    # старый нижний угол убран
    assert "base + ZONE_H - 52" not in source


def test_tree_and_chips_survive_taps():
    """Тап и покупка возвращают полное состояние, а не обрезанное."""
    assert "async def _yugi_state(" in open("app/webapp.py", encoding="utf-8").read()
    assert YUGI_PAGE.count("tree_pool") >= 1
    # страница берёт состояние из ответа на покупку узла
    assert "if (r && r.tree_pool){ S.data = r; render(); }" in YUGI_PAGE
