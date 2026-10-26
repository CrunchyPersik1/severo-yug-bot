"""Опыт по локациям, HUD без наложений, пузыри чата над игроком."""

from app.webapp import DUNGEON_PAGE


def test_zone_gate_is_25_levels():
    assert "function zoneReq(y){ return 1 + zoneIndex(y) * 25; }" in DUNGEON_PAGE
    assert "function ownZone(lvl){" in DUNGEON_PAGE
    # своя локация: 1-25 -> 1, 26-50 -> 2
    assert "Math.floor((Math.max(1, lvl | 0) - 1) / 25)" in DUNGEON_PAGE


def test_xp_scales_with_own_zone():
    assert "function zoneXpMult(mobZone, lvl){" in DUNGEON_PAGE
    # ниже своей локации опыт падает, пол — ровно в 10 раз
    assert "Math.max(0.1, Math.pow(0.45, -d))" in DUNGEON_PAGE
    # и это применяется при убийстве моба
    assert "const mult = zoneXpMult(zoneIndex(m.y), stats.lvl)" in DUNGEON_PAGE


def test_hud_has_no_stubs_and_is_split():
    # три строки HUD: состояние, ряд кнопок, мир
    assert 'class="top bar"' in DUNGEON_PAGE
    assert 'class="top2"' in DUNGEON_PAGE
    assert 'class="zlbl" id="zone"' in DUNGEON_PAGE
    # заглушка заданий убрана — кнопка ведёт на страницу
    assert "Задания — заглушка прототипа" not in DUNGEON_PAGE
    assert 'if (t === "quests"){ location.href = "/quests"; return; }' in DUNGEON_PAGE
    # оружие открывается попапом, а не висит поверх джойстика
    assert "if (t === \"weapon\"){" in DUNGEON_PAGE
    assert "#wpanel.on{display:flex" in DUNGEON_PAGE
    assert 'id="wback"' in DUNGEON_PAGE


def test_chat_bubbles_have_player_id():
    # причина «пузырь не там»: applyPlayers не копировал id, и BUBBLES[r.id] пуст
    assert "r.id = p.id;" in DUNGEON_PAGE
    assert "const bubble = BUBBLES[r.id];" in DUNGEON_PAGE
    # пузырь выше ника и с хвостиком к голове
    assert "const bx = x - width / 2, by = y - 88;" in DUNGEON_PAGE
