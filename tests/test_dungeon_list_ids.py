"""Телепорт и лидерборд не должны путать списки."""

import re

from app.webapp import DUNGEON_PAGE


def test_teleport_and_top_use_their_own_lists():
    # раньше оба рисовали в один список: телепорт уходил в лидерборд и наоборот
    assert 'document.getElementById("zlist")' in DUNGEON_PAGE
    assert 'document.getElementById("tplist")' in DUNGEON_PAGE

    teleport = re.search(r"function buildTeleport\(\)\{(.*?)\n\}", DUNGEON_PAGE, re.S)
    top = re.search(r"async function openTop\(\)\{(.*?)\n\}", DUNGEON_PAGE, re.S)
    assert teleport and top
    assert 'getElementById("zlist")' in teleport.group(1)
    assert 'getElementById("tplist")' in top.group(1)
    assert 'getElementById("tplist")' not in teleport.group(1)
    assert 'getElementById("zlist")' not in top.group(1)


def test_markup_has_both_containers():
    assert 'id="zmenu"' in DUNGEON_PAGE
    assert 'id="zlist"' in DUNGEON_PAGE
    assert 'id="tplist"' in DUNGEON_PAGE
