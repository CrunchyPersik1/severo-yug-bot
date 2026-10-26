"""Мини-аппка: кликер, подземелье и задания связаны между собой."""

from app.webapp import DUNGEON_PAGE, QUESTS_PAGE, YUGI_PAGE


def test_switcher_on_clicker_and_quests():
    for page, name in ((YUGI_PAGE, "кликер"), (QUESTS_PAGE, "задания")):
        assert 'class="apps"' in page, name
        assert 'href="/yugi"' in page, name
        assert 'href="/proto_dungeon"' in page, name
        assert 'href="/quests"' in page, name
        assert page.count('class="on" href') == 1, name


def test_dungeon_links_to_other_sections():
    # в подземелье нет пилюли-переключателя: сверху группы кнопок,
    # а переходы в разделы живут в полном меню (кнопка ⤢)
    assert 'class="apps"' not in DUNGEON_PAGE
    assert 'href="/yugi"' in DUNGEON_PAGE
    assert 'href="/quests"' in DUNGEON_PAGE
    assert 'data-tab="clicker" title="Назад в кликер"' in DUNGEON_PAGE
    assert 'id="wfull"' in DUNGEON_PAGE


def test_dungeon_back_button_goes_to_clicker():
    assert 'if (t === "clicker"){ location.href = "/yugi"; return; }' in DUNGEON_PAGE
    assert "Вернуться в кликер — в большой версии" not in DUNGEON_PAGE


def test_hub_lists_dungeon_and_quests():
    from app import webapp

    paths = [s.get("path") for s in webapp.HUB_SECTIONS]
    assert "/proto_dungeon" in paths
    assert "/quests" in paths
    assert "/yugi" in paths
