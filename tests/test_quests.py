"""Тесты наград за квесты: у каждого своя."""

from app import event_week, quests


def test_seven_quests_from_event_sources():
    names = quests.order()
    assert len(names) == 7
    assert names == tuple(event_week.ORDER)
    for key in names:
        assert quests.title_for(key)
        assert quests.need_for(key) >= 1
        assert quests.source_sql(key)


def test_every_quest_has_its_own_reward():
    rewards = [quests.reward_for(key) for key in quests.order()]
    # никаких семи одинаковых «очки + кейс»
    assert len({tuple(sorted(r.items())) for r in rewards}) == len(rewards)
    # и не только очки с кейсами: встречаются крутки, дропы и Юги
    kinds = set()
    for reward in rewards:
        kinds.update(reward.keys())
    assert {"points", "cases", "roulette", "drops", "yugi"} <= kinds


def test_texts_are_human():
    assert quests.reward_text({"cases": 2}) == "2 кейса"
    assert quests.reward_text({"cases": 3}) == "3 кейса"
    assert quests.reward_text({"cases": 5}) == "5 кейсов"
    assert quests.reward_text({"roulette": 2}) == "2 крутки"
    assert quests.reward_text({"roulette": 5}) == "5 круток"
    assert quests.reward_text({"drops": 3}) == "3 дропа"
    assert quests.reward_text({"yugi": 500}) == "500 Югов"
    assert quests.reward_text({"points": 20_000}) == "20 000 очков"
    assert quests.reward_text({"points": 25_000, "cases": 1}) == "25 000 очков + 1 кейс"


def test_reward_by_index_matches_key():
    for index, key in enumerate(quests.order()):
        assert quests.reward_for(index) == quests.reward_for(key)


def test_unknown_key_gets_fallback():
    assert quests.reward_for("нет такого") == {"points": quests.POINTS}
    assert quests.source_sql("нет такого") is None
    assert quests.title_for("нет такого") == "нет такого"
