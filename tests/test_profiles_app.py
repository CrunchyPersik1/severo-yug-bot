"""Профили: ссылки ?u=, кликабельные лидеры, карточка в хабе."""

from app.webapp import HUB_PAGE, PROFILE_PAGE


def test_profile_page_opens_user_from_query():
    assert 'new URLSearchParams(location.search).get("u")' in PROFILE_PAGE
    assert "open(startUser ? +startUser : 0);" in PROFILE_PAGE
    # прямой заход без параметра открывает свой профиль
    assert "open(0);" not in PROFILE_PAGE


def test_hub_leaderboard_rows_are_tappable():
    assert 'class="line tap" data-u=' in HUB_PAGE
    assert "loadProfile(+el.dataset.u)" in HUB_PAGE


def test_hub_profile_card_like_miniapp():
    for marker in ('pcard', 'pbn', 'pav', 'pgrid', 'ptags', 'profQ', 'profSearch'):
        assert marker in HUB_PAGE, marker
    # карточка грузится из того же API, что и мини-апп
    assert '/api/profile" + (userId ? "?u=" + userId : "")' in HUB_PAGE
    assert "/api/profile/search?q=" in HUB_PAGE
    assert "Открыть страницу" in HUB_PAGE
