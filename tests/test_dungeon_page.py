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


def test_single_inline_script_block():
    # один инлайн-скрипт страницы плюс подключение телеграм-скрипта тегом с src
    assert len(re.findall(r"<script>", DUNGEON_PAGE)) == 1
    assert DUNGEON_PAGE.count("</script>") == 2


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
    assert "bs.t >= BOSS_WAIT" in DUNGEON_PAGE
    assert "startBattle()" in DUNGEON_PAGE
    assert "bossEngage(bs)" in DUNGEON_PAGE
    assert "zoneReq(bs.y)" in DUNGEON_PAGE
    assert "P.bossCd" in DUNGEON_PAGE


def test_coop_overlay_and_api():
    assert 'id="coop"' in DUNGEON_PAGE
    assert 'id="chit"' in DUNGEON_PAGE
    assert "const BOSS_WAIT = 10;" in DUNGEON_PAGE
    for path in ("/api/dungeon/boss/join", "/api/dungeon/boss/state",
                 "/api/dungeon/boss/hit", "/api/dungeon/boss/leave",
                 "/api/dungeon/boss/start"):
        assert path in DUNGEON_PAGE, path
    assert "X-Telegram-Init-Data" in DUNGEON_PAGE


def test_telegram_script_is_loaded():
    """Без скрипта Telegram initData пустой и кооп не работает вообще."""
    assert "telegram-web-app.js" in DUNGEON_PAGE
    assert "Telegram.WebApp.initData" in DUNGEON_PAGE
    assert "Telegram.WebApp.ready()" in DUNGEON_PAGE


def test_hint_when_opened_outside_bot():
    """Открыли ссылкой в браузере — говорим об этом прямо на экране."""
    assert "КООП НЕДОСТУПЕН" in DUNGEON_PAGE
    assert "#tghint" in DUNGEON_PAGE


def test_weapon_upgrade_is_wired():
    assert "function heroUpgrade(" in DUNGEON_PAGE
    assert "/api/dungeon/upgrade" in DUNGEON_PAGE
    assert "HERO_OFFER" in DUNGEON_PAGE
    assert "УЛУЧШИТЬ · " in DUNGEON_PAGE
    assert "Улучшение оружия — за монеты" not in DUNGEON_PAGE


def test_chat_panel_is_wired():
    assert 'id="chat"' in DUNGEON_PAGE
    assert 'id="chtext"' in DUNGEON_PAGE
    assert "function chatSend(" in DUNGEON_PAGE
    assert 'type: "chat"' in DUNGEON_PAGE            # кадр по сокету
    assert 'data.type === "chat"' in DUNGEON_PAGE    # приём
    assert "Чат — в большой версии" not in DUNGEON_PAGE
    assert "BUBBLES" in DUNGEON_PAGE                  # пузырь над героем


def test_boss_reward_is_applied_once():
    assert "room.reward" in DUNGEON_PAGE
    assert "COOP.rewarded" in DUNGEON_PAGE


def test_live_players_on_map():
    """Другие игроки видны в реальном времени, заглушек OFFLINE больше нет."""
    assert "/ws/dungeon" in DUNGEON_PAGE            # основной транспорт
    assert "function wsStart(" in DUNGEON_PAGE
    assert "/api/dungeon/presence" in DUNGEON_PAGE   # запасной путь
    assert "function drawRemote(" in DUNGEON_PAGE
    assert "const REMOTE = {}" in DUNGEON_PAGE
    assert "remoteTick(dt)" in DUNGEON_PAGE
    assert "OFFLINE" not in DUNGEON_PAGE
    assert "npcs" not in DUNGEON_PAGE


def test_mobs_live_in_neighbour_zones():
    # раньше мобы спавнились только в зоне игрока, соседние локации пустовали
    assert "function spawnOne(zi)" in DUNGEON_PAGE
    assert "MOB_PER_NEAR" in DUNGEON_PAGE
    assert "mobsInZone" in DUNGEON_PAGE
    assert "MOB_KEEP_ZONES" in DUNGEON_PAGE
    assert "fillMobs()" in DUNGEON_PAGE


def test_death_returns_to_base_not_middle():
    # WORLD.h / 2 — это середина карты, игрока уносило на середину
    assert "P.y = WORLD.h / 2" not in DUNGEON_PAGE
    assert "P.y = WORLD.h - 260;" in DUNGEON_PAGE


def test_graphics_panel_replaces_stub():
    assert "Настройки — заглушка" not in DUNGEON_PAGE
    assert "function openGfx()" in DUNGEON_PAGE
    assert "openGfx(); return;" in DUNGEON_PAGE
    assert 'data-fx=' in DUNGEON_PAGE
    assert "FX.setLevel" in DUNGEON_PAGE
