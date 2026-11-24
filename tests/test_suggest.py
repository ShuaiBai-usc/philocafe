"""Suggested next messages (design doc 7.9, FR-46)."""

import pytest

from app.fakes import FAKE_QUOTING_REPLY, FakeVoice, fake_deps
from app.graph import build_graph, run_turn
from app.suggest import NextFilter, parse


def split(pieces):
    f = NextFilter()
    out = "".join(f.feed(p) for p in pieces) + f.close()
    return out, parse(f.block)


@pytest.mark.parametrize("pieces", [
    ["Good point?\n<next>\nWhy?\nAnd then?\n</next>"],
    ["Good point?", "\n<ne", "xt>\nWhy?\nAnd", " then?\n</next>"],
    ["Good point?\n<", "n", "e", "x", "t", ">", "Why?\nAnd then?"],          # unclosed: still parsed
])
def test_block_is_held_back_and_parsed(pieces):
    out, items = split(pieces)
    assert out == "Good point?" and items == ["Why?", "And then?"]


def test_text_that_only_looks_like_the_tag_passes():
    assert split(["a <ne", "w idea>"]) == ("a <new idea>", [])
    assert split(["ends with <"]) == ("ends with <", [])


def test_parse_cleans_and_limits():
    block = "\n1. “Why?”\n- why?\n• Is it fair?\n(3) What about friends?\n" + "x" * 90 + "\nFourth one\n</next> junk"
    assert parse(block) == ["Why?", "Is it fair?", "What about friends?"]
    assert parse(None) == [] and parse("") == []


def events(graph, text, thread="t"):
    return list(run_turn(graph, thread, text, "socrates"))


def test_suggestions_event_after_the_reply_and_stored():
    graph = build_graph(fake_deps(generate=FakeVoice([w + " " for w in FAKE_QUOTING_REPLY.split(" ")])))
    evs = events(graph, "is virtue teachable")
    kinds = [e["type"] for e in evs]
    sug = [e["data"] for e in evs if e["type"] == "suggestions"]
    assert sug == [{"items": ["Can a bad person become good?", "Is being good the same as being kind?"]}]
    assert kinds.index("suggestions") > max(i for i, k in enumerate(kinds) if k == "token")
    state = graph.get_state({"configurable": {"thread_id": "t"}}).values
    assert "<next>" not in state["reply"] and "Can a bad person" not in state["reply"]
    assert state["messages"][-1].additional_kwargs["suggestions"] == sug[0]["items"]
    assert "".join(e["data"]["text"] for e in evs if e["type"] == "token").rstrip().endswith("makes a person good?")


def test_no_suggestions_from_tier_2_or_at_an_exit():
    voice = FakeVoice([FAKE_QUOTING_REPLY])
    graph = build_graph(fake_deps(generate=voice))
    assert not [e for e in events(graph, "TEST_TIER2 hmm") if e["type"] == "suggestions"]
    assert not [e for e in events(graph, "TEST_TIER3", "u") if e["type"] == "suggestions"]


def test_quote_inside_suggestions_is_not_checked_or_shown():
    voice = FakeVoice(['<mood label="curious" intensity="0.5"/>Hm.\n<next>\n<q id="x">fake</q> line\nWhy?\n</next>'])
    evs = events(build_graph(fake_deps(generate=voice)), "hello")
    assert [e["data"] for e in evs if e["type"] == "suggestions"] == [{"items": ["Why?"]}]
    assert not [e for e in evs if e["type"] == "citation"]
