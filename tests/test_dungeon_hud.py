"""HUD по референсу: рамки, группы кнопок, меню из половин."""

from app.webapp import DUNGEON_PAGE


def test_top_is_two_framed_groups():
    assert 'class="hudtop"' in DUNGEON_PAGE
    # слева: назад в кликер, сумка, задания, квест НПС
    assert 'data-tab="clicker" title="Назад в кликер"' in DUNGEON_PAGE
    assert 'data-tab="bag"' in DUNGEON_PAGE
    assert 'data-tab="quests"' in DUNGEON_PAGE
    assert 'id="questbtn"' in DUNGEON_PAGE
    # справа: лидеры, кто оффлайн, настройки
    assert 'data-tab="board"' in DUNGEON_PAGE
    assert 'id="offbtn"' in DUNGEON_PAGE
    assert 'data-tab="settings"' in DUNGEON_PAGE
    # монеты по центру, зона — там же
    assert 'class="zlbl"' in DUNGEON_PAGE


def test_bottom_menu_is_split():
    assert 'class="wmenu" id="wpanel"' in DUNGEON_PAGE
    assert "ОРУЖИЕ" in DUNGEON_PAGE
    assert "СТАТИСТИКА ОРУЖИЯ" in DUNGEON_PAGE
    # кнопки действий на месте, id сохранены (их дёргает JS)
    for marker in ('id="warmor"', 'id="wupg"', 'id="wchat"',
                   'id="wname"', 'id="wdmg"', 'id="wrange"', 'id="wspd"'):
        assert marker in DUNGEON_PAGE, marker


def test_full_menu_opens():
    assert 'id="wfull"' in DUNGEON_PAGE
    assert 'id="wexpand"' in DUNGEON_PAGE
    assert 'id="wclose"' in DUNGEON_PAGE
    # в полном меню — переходы в другие разделы
    for path in ('/stocks', '/upgrader', '/case_app', '/profile', '/hub'):
        assert 'href="%s"' % path in DUNGEON_PAGE, path


def test_offline_button_lists_players():
    assert 'document.getElementById("offbtn").onclick' in DUNGEON_PAGE
    assert "Спят в углу" in DUNGEON_PAGE


def test_controls_do_not_overlap_menu():
    # джойстик и кнопки подняты над меню, полосы — выше них
    assert "left:14px;bottom:150px" in DUNGEON_PAGE
    assert "right:14px;bottom:150px" in DUNGEON_PAGE
    # полосы теперь компактной строкой сверху, а не поверх игры
    assert "top:54px" in DUNGEON_PAGE


def test_hud_buttons_are_actually_wired():
    """Регрессия: селектор был .top, разметка — .hudtop, и все 5 кнопок молчали."""
    assert 'document.querySelectorAll(".hudtop [data-tab]")' in DUNGEON_PAGE
    assert 'document.querySelectorAll(".top [data-tab]")' not in DUNGEON_PAGE
    # обработчик вешается через общий диспетчер, а не копией кода в пяти местах
    assert "function openTab(t){" in DUNGEON_PAGE
    for tab in ("bag", "clicker", "quests", "weapon", "board", "settings"):
        assert 't === "%s"' % tab in DUNGEON_PAGE, tab


def test_css_selectors_match_the_markup():
    """.top в стилях подземелья не существовал в разметке — стили не доезжали."""
    assert ".hudtop .grp{display:flex;gap:7px}" in DUNGEON_PAGE
    assert ".hudtop button{" in DUNGEON_PAGE
    # старый селектор, который ни на что не накладывался, убран
    assert ".top button{border:0;color:#f0d79a" not in DUNGEON_PAGE
    assert ".top .grp{display:flex;gap:7px}" not in DUNGEON_PAGE


def test_bag_opens_from_one_place():
    """В сумку нельзя было войти: кнопки звали несуществующий #bagbtn."""
    assert "function openBag(){" in DUNGEON_PAGE
    assert "function closeBag(){" in DUNGEON_PAGE
    assert 'if (t === "bag"){ openBag(); return; }' in DUNGEON_PAGE
    assert '["bagbtn", "bag2"].forEach' in DUNGEON_PAGE
    assert "if (bagClose) bagClose.onclick = closeBag;" in DUNGEON_PAGE


def test_bag_skips_unknown_weapons_instead_of_crashing():
    """paintInv падал на weaponById(...).name, если оружия уже нет в WEAPONS."""
    assert "const w = weaponById(id);" in DUNGEON_PAGE
    assert 'if (!w) return "";' in DUNGEON_PAGE
    assert 'if (!picked){ toast("Это оружие больше не существует"); return; }' in DUNGEON_PAGE
