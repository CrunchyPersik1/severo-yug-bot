"""Мини-аппка: кликер, подземелье и задания под одним переключателем."""

from app.webapp import DUNGEON_PAGE, QUESTS_PAGE, YUGI_PAGE


def test_switcher_on_all_three_pages():
    for page, name in ((YUGI_PAGE, "кликер"), (DUNGEON_PAGE, "подземелье"),
                       (QUESTS_PAGE, "задания")):
        assert 'class="apps"' in page, name
        assert 'href="/yugi"' in page, name
        assert 'href="/proto_dungeon"' in page, name
        assert 'href="/quests"' in page, name
        # ровно одна активная вкладка
        assert page.count('class="on" href') == 1 or page.count(' class="on"') >= 1, name


def test_dungeon_back_button_goes_to_clicker():
    assert 'if (t === "clicker"){ location.href = "/yugi"; return; }' in DUNGEON_PAGE
    assert "Вернуться в кликер — в большой версии" not in DUNGEON_PAGE


def test_hub_lists_dungeon_and_quests():
    from app import webapp

    paths = [s.get("path") for s in webapp.HUB_SECTIONS]
    assert "/proto_dungeon" in paths
    assert "/quests" in paths
    assert "/yugi" in paths
