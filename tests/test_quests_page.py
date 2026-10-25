"""Страница «Задания»: кнопка «забрать» на месте."""

import re

from app.webapp import QUESTS_PAGE


def test_page_has_single_inline_script():
    assert len(re.findall(r"<script>", QUESTS_PAGE)) == 1


def test_claim_button_is_wired():
    assert "data-claim=" in QUESTS_PAGE
    assert "/api/quests/claim" in QUESTS_PAGE
    assert "ЗАБРАТЬ" in QUESTS_PAGE
    assert "ПОЛУЧЕНО" in QUESTS_PAGE
    assert "reward_text" in QUESTS_PAGE


def test_note_no_longer_promises_automatic_rewards():
    assert "Награды приходят автоматически" not in QUESTS_PAGE
    assert "забирается кнопкой" in QUESTS_PAGE
