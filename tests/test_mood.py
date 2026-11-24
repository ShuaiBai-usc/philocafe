"""Persona mood (design doc 7.5, FR-15 to FR-17, FR-34, FR-66)."""

import pytest

from app.fakes import FakeVoice, fake_deps
from app.graph import build_graph, run_turn
from app.mood import FALLBACK, LOCKED, MoodTagFilter, next_mood, parse_tag
from app.personas import load_personas
from app.persona import system_prompt

MOODS = ("curious", "amused", "skeptical", "pondering", "pleased", "attentive")


def strip(pieces):
    f = MoodTagFilter(MOODS)
    out = "".join(f.feed(p) for p in pieces) + f.close()
    return f.tag, out


@pytest.mark.parametrize("pieces, tag, text", [
    (['<mood label="amused" intensity="0.4"/> Ha, ', "well."], ("amused", 0.4), "Ha, well."),
    (["<", "mo", 'od label="pondering" ', 'intensity="0.9"/>', "Hmm."], ("pondering", 0.9), "Hmm."),
    (["  <MOOD label='x'/>Hi"], FALLBACK, "Hi"),                         # malformed tag: dropped, attentive
    (['<mood label="furious" intensity="0.9"/>No.'], FALLBACK, "No."),   # not in the set
    (['<mood label="curious" intensity="2"/>No.'], FALLBACK, "No."),     # out of range
    (["Just talking."], FALLBACK, "Just talking."),
    (['<q id="a">quoted</q> words'], FALLBACK, '<q id="a">quoted</q> words'),
    ([""], FALLBACK, ""),
])
def test_filter_takes_the_tag_off(pieces, tag, text):
    got_tag, out = strip(pieces)
    assert got_tag == tag and out == text


def test_parse_tag_ignores_case_and_order():
    assert parse_tag('intensity="0.5" LABEL="Curious"', MOODS) == ("curious", 0.5)


def test_smoothing_waits_a_turn_unless_strong():
    m, cand = next_mood(None, None, "curious", 0.6)
    assert m == {"label": "curious", "intensity": 0.6, "locked": False} and cand is None
    m, cand = next_mood(m, cand, "amused", 0.4)          # new label, weak: wait
    assert m["label"] == "curious" and m["intensity"] == 0.5 and cand == "amused"
    m, cand = next_mood(m, cand, "amused", 0.4)          # second turn in a row: switch
    assert m["label"] == "amused" and cand is None
    m, cand = next_mood(m, cand, "skeptical", 0.85)      # strong: switch at once
    assert m["label"] == "skeptical"
    m, cand = next_mood(dict(LOCKED), None, "pleased", 0.3)   # after the lock lifts, start fresh
    assert m == {"label": "pleased", "intensity": 0.3, "locked": False}


def test_every_persona_has_a_valid_mood_set_and_the_rule_in_its_prompt():
    for p in load_personas().values():
        assert "attentive" in p.moods and len(p.moods) <= 6
        assert all(m in system_prompt(p) for m in p.moods) and "<mood" in system_prompt(p)


def run(graph, text, thread="t"):
    return list(run_turn(graph, thread, text, "socrates"))


def moods(events):
    return [e["data"] for e in events if e["type"] == "mood"]


def test_mood_is_carried_in_state_and_on_the_reply():
    graph = build_graph(fake_deps())
    run(graph, "hello")
    state = graph.get_state({"configurable": {"thread_id": "t"}}).values
    assert state["mood"]["label"] == "curious"
    assert state["messages"][-1].additional_kwargs["mood"] == state["mood"]
    assert "<mood" not in state["messages"][-1].content and "<mood" not in state["reply"]


def test_tier2_locks_the_mood_and_ignores_the_tag():
    graph = build_graph(fake_deps())
    events = run(graph, "TEST_TIER2 hello")
    assert moods(events) == [dict(LOCKED)]
    first = [e["type"] for e in events].index("mood")
    assert first < [e["type"] for e in events].index("token")


def test_exit_locks_and_the_return_unlocks():
    graph = build_graph(fake_deps())
    events = run(graph, "TEST_TIER3")
    assert moods(events) == [dict(LOCKED)]
    events = run(graph, "TEST_COME_BACK please")
    assert moods(events) == [{"label": "curious", "intensity": 0.6, "locked": False}]


def test_a_reply_without_a_tag_falls_back_to_attentive():
    graph = build_graph(fake_deps(generate=FakeVoice(reply=["No tag here."])))
    events = run(graph, "hello")
    assert moods(events) == [{"label": "attentive", "intensity": 0.3, "locked": False}]
    assert "".join(e["data"]["text"] for e in events if e["type"] == "token") == "No tag here."
