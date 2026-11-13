"""НПС-квестовик на карте и меню без вылезающих кнопок."""

from app.webapp import DUNGEON_PAGE


def test_npc_stands_near_spawn():
    assert "const NPC = {" in DUNGEON_PAGE
    assert "function npcSpot(){" in DUNGEON_PAGE
    # позиция считается от мира: чуть правее спавна в первой локации
    assert "return {x: WORLD.w / 2 + 78, y: WORLD.h - 248};" in DUNGEON_PAGE
    assert "function npcDraw(t){" in DUNGEON_PAGE
    assert "npcDraw(animT);" in DUNGEON_PAGE
    # имя и «!» над головой
    assert "NPC.name" in DUNGEON_PAGE


def test_npc_talks():
    assert "greet: [" in DUNGEON_PAGE
    # при подходе окликает, но панель сама не распахивается: иначе мобы бьют
    # игрока, пока он читает задание
    assert "if (!NPC.met && npcDist() < 110){" in DUNGEON_PAGE
    met_block = DUNGEON_PAGE.split("if (!NPC.met && npcDist() < 110){", 1)[1][:400]
    assert "questOpen()" not in met_block, "подход к НПС не должен открывать квест сам"
    # в панели реплика НПС, а не сухая строка
    assert "NPC.name + ': «' + esc(line) + '»'" in DUNGEON_PAGE


def test_quest_panel_pauses_the_world():
    """Пока панель квеста открыта, мобы не должны бить игрока."""
    assert "let questShown = false;" in DUNGEON_PAGE
    assert "questShown = true;" in DUNGEON_PAGE
    assert "questShown = false;" in DUNGEON_PAGE
    assert "COOP.open || questShown){ render(dt); return; }" in DUNGEON_PAGE


def test_quest_panel_has_money_helper():
    """Раньше page падал на ReferenceError: money is not defined."""
    assert "function money(n){" in DUNGEON_PAGE
    # и правда используется в панели квеста
    assert "money(QUEST.coins)" in DUNGEON_PAGE
    assert "money(r.coins)" in DUNGEON_PAGE


def test_quest_progress_survives_reload():
    """Прогресс копится на клиенте — жёсткий сброс обнулял полоску."""
    assert "QUEST.done = 0; QUEST.bossDone = 0;" not in DUNGEON_PAGE
    assert "const sameHour = !!QUEST && QUEST.hour === r.quest.hour;" in DUNGEON_PAGE
    assert "const keepDone = sameHour ? (QUEST.done || 0) : 0;" in DUNGEON_PAGE


def test_npc_can_be_tapped():
    assert 'cv.addEventListener("pointerdown"' in DUNGEON_PAGE
    assert "if (Math.hypot(wx - spot.x, wy - spot.y) < 70) questOpen();" in DUNGEON_PAGE
    # и надёжная кнопка рядом с ним
    assert 'id="talkbtn"' in DUNGEON_PAGE
    assert 'document.getElementById("talkbtn").onclick = questOpen;' in DUNGEON_PAGE
    assert 'npcDist() < 150' in DUNGEON_PAGE


def test_quest_panel_reports_errors():
    # раньше ошибка загрузки глоталась и панель выглядела «сломанной»
    assert 'QUEST_ERR = (r && r.error) || "сервер не ответил"' in DUNGEON_PAGE
    assert 'toast("Квест: " + QUEST_ERR)' in DUNGEON_PAGE
    # и кнопка повтора прямо в панели
    assert 'id="qretry"' in DUNGEON_PAGE
    assert 'if (retry) retry.onclick = questLoad;' in DUNGEON_PAGE


def test_stats_and_buttons_fit():
    # статы — сетка из трёх колонок, кнопки — только иконки с ценой
    assert ".wstats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr))" in DUNGEON_PAGE
    assert '("🛡" + HERO_ARMOR.price)' in DUNGEON_PAGE
    assert '("⬆" + HERO_OFFER.price)' in DUNGEON_PAGE
    assert ".wmenu .wcol{overflow:hidden}" in DUNGEON_PAGE
