"""Страница «Подземелья Тимура»: структура, шейдеры, включённый бой с боссом."""

import re
from html.parser import HTMLParser

from app.webapp import DUNGEON_PAGE


class _Ids(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key == "id" and value:
                self.ids.append(value)


def test_page_parses_and_ids_are_unique():
    parser = _Ids()
    parser.feed(DUNGEON_PAGE)
    assert len(parser.ids) == len(set(parser.ids)), "id на странице повторяются"
    assert {"cv", "fx", "gfx", "toast", "attack", "shield", "ability"} <= set(parser.ids)


def test_single_script_block():
    assert DUNGEON_PAGE.count("<script>") == 1
    assert DUNGEON_PAGE.count("</script>") == 1


def test_fx_shaders_are_balanced_glsl():
    shaders = re.findall(r"const (VS|FS_\w+) = `(.*?)`;", DUNGEON_PAGE, re.S)
    assert len(shaders) == 5, [name for name, _ in shaders]
    for name, source in shaders:
        assert "void main" in source, name
        assert source.count("{") == source.count("}"), name
        assert "\\" not in source, name
        for line in source.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                assert stripped[-1] in ";{})", (name, stripped)


def test_no_smoothstep_with_reversed_edges():
    # на части мобильных драйверов это неопределённое поведение
    assert "smoothstep(1.05, 0.28" not in DUNGEON_PAGE


def test_bloom_has_downsample_chain():
    assert "allocLevels" in DUNGEON_PAGE
    assert "1 << (i + 1)" in DUNGEON_PAGE
    assert "globalCompositeOperation" in DUNGEON_PAGE  # запасной 2D-блум


def test_boss_battle_is_wired_up():
    assert "bs.t >= 5" in DUNGEON_PAGE
    assert "startBattle()" in DUNGEON_PAGE
    assert "zoneReq(bs.y)" in DUNGEON_PAGE
    assert "P.bossCd" in DUNGEON_PAGE


def test_graphics_panel_replaces_stub():
    assert "Настройки — заглушка" not in DUNGEON_PAGE
    assert "function openGfx()" in DUNGEON_PAGE
    assert "openGfx(); return;" in DUNGEON_PAGE
    assert 'data-fx=' in DUNGEON_PAGE
    assert "FX.setLevel" in DUNGEON_PAGE
