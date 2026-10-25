"""Квесты со страницы «Задания»: награда и одноразовость."""

from app import event_week, quests


def test_seven_quests_from_event_sources():
    names = quests.order()
    assert len(names) == 7
    assert names == tuple(event_week.ORDER)
    for key in names:
        assert quests.title_for(key)
        assert quests.need_for(key) >= 1
        assert quests.source_sql(key)


def test_reward_every_other_quest_has_a_case():
    rewards = [quests.reward_for(index) for index in range(7)]
    assert all(item["points"] == quests.POINTS for item in rewards)
    assert [bool(item.get("cases")) for item in rewards] == [
        False, True, False, True, False, True, False
    ]


def test_reward_text_mentions_points():
    text = quests.reward_text(quests.reward_for(0))
    assert "очк" in text.lower()
    text_with_case = quests.reward_text(quests.reward_for(1))
    assert "кейс" in text_with_case.lower()


def test_unknown_key_has_no_source():
    assert quests.source_sql("нет такого") is None
    assert quests.title_for("нет такого") == "нет такого"
