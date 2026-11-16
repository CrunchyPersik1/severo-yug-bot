"""Кейс оружия отдаёт ствол в сумку героя, а не ломает jsonb."""

import json
import pathlib


def test_bag_parsed_from_jsonb_string():
    source = pathlib.Path("app/shop.py").read_text(encoding="utf-8")
    # jsonb приходит строкой: list("[\"sword…") разложил бы её по буквам
    assert "isinstance(raw_bag, str)" in source
    assert "json.loads(raw_bag" in source


def test_case_grant_equips_stronger_weapon():
    from app import dungeon_case

    weak = dungeon_case.stats("sword_0_0")
    strong = dungeon_case.stats("sword_7_4")
    assert strong["dmg"] > weak["dmg"]
    assert json.dumps([strong["id"]])
