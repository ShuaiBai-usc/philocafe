"""Graph skeleton: routing, events, checkpoint and fail-closed safety. Offline only."""

import pytest

from app.config import SafetyConfig
from app.fakes import FAKE_CHUNKS, FAKE_REPLY, FakeSafetyModel, FakeVoice, fake_deps
from app.graph import build_graph, run_turn
from app.safety.node import decide


def run(graph, text, thread="t1"):
    return list(run_turn(graph, thread, text, "socrates"))


def types(events):
    return [e["type"] for e in events]


def by_type(events, type_):
    return [e["data"] for e in events if e["type"] == type_]


def test_tier0_runs_persona_and_streams_in_order():
    graph = build_graph(fake_deps())
    events = run(graph, "is virtue teachable")
    assert types(events) == ["safety", "voice"] + ["token"] * len(FAKE_REPLY) + ["trace", "done"]
    assert by_type(events, "voice") == [{"speaker": "persona", "persona_id": "socrates"}]
    assert "".join(t["text"] for t in by_type(events, "token")) == "".join(FAKE_REPLY)
    trace = by_type(events, "trace")[0]
    assert [n["name"] for n in trace["nodes"]] == ["safety", "moderator", "persona"]
    assert trace["retrieved"] == [c["chunk_id"] for c in FAKE_CHUNKS]
    assert trace["skipped"] == []


def test_tier3_goes_to_exit_without_calling_persona():
    voice = FakeVoice()
    graph = build_graph(fake_deps(generate=voice))
    events = run(graph, "TEST_TIER3")
    assert voice.calls == 0
    assert by_type(events, "safety")[0]["tier"] == 3
    assert by_type(events, "voice") == [{"speaker": "system", "persona_id": None}]
    assert by_type(events, "exit")[0]["reason"] == "tier_3"
    assert [n["name"] for n in by_type(events, "trace")[0]["nodes"]] == ["safety", "exit"]
    assert graph.get_state({"configurable": {"thread_id": "t1"}}).values["mode"] == "support"


def test_support_mode_lasts_for_the_thread():
    voice = FakeVoice()
    graph = build_graph(fake_deps(generate=voice))
    run(graph, "TEST_TIER3")
    events = run(graph, "an everyday question")
    assert voice.calls == 0
    assert by_type(events, "exit")[0]["reason"] == "support_mode"
    # A new thread starts in persona mode again.
    run(graph, "an everyday question", thread="t2")
    assert voice.calls == 1


def test_tier2_stays_with_persona_at_midterm():
    voice = FakeVoice()
    graph = build_graph(fake_deps(generate=voice))
    events = run(graph, "TEST_TIER2")
    assert by_type(events, "safety")[0]["tier"] == 2
    assert voice.calls == 1


def test_checkpoint_keeps_messages_per_thread():
    graph = build_graph(fake_deps())
    run(graph, "first")
    run(graph, "second")
    run(graph, "other thread", thread="t2")
    messages = graph.get_state({"configurable": {"thread_id": "t1"}}).values["messages"]
    assert [m.content for m in messages[::2]] == ["first", "second"]
    assert len(messages) == 4
    assert len(graph.get_state({"configurable": {"thread_id": "t2"}}).values["messages"]) == 2


def test_trace_is_reset_each_turn():
    graph = build_graph(fake_deps())
    run(graph, "first")
    events = run(graph, "second")
    assert len(by_type(events, "trace")[0]["nodes"]) == 3


def test_jev_failure_uses_fallback():
    jev, fallback = FakeSafetyModel("jev", fail=True), FakeSafetyModel("fallback")
    graph = build_graph(fake_deps(safety_models=[jev, fallback]))
    safety = by_type(run(graph, "hello"), "safety")[0]
    assert (jev.calls, fallback.calls) == (1, 1)
    assert safety["source"] == "fallback"
    assert safety["tier"] == 0


def test_every_safety_model_failing_escalates():
    voice = FakeVoice()
    models = [FakeSafetyModel("jev", fail=True), FakeSafetyModel("fallback", fail=True)]
    graph = build_graph(fake_deps(safety_models=models, generate=voice))
    events = run(graph, "hello")
    safety = by_type(events, "safety")[0]
    assert safety["tier"] == 3
    assert safety["model_version"] == "fail-closed"
    assert voice.calls == 0
    assert by_type(events, "exit")


def test_node_error_becomes_error_event():
    graph = build_graph(fake_deps(generate=FakeVoice(fail=True)))
    events = run(graph, "hello")
    assert events[-1]["type"] == "error"
    assert "done" not in types(events)


@pytest.mark.parametrize("probs, expected", [
    ({0: 0.5, 1: 0.0, 2: 0.0, 3: 0.5}, (3, 0.5, 0.5)),     # P(3) exactly at theta3
    ({0: 0.5, 1: 0.0, 2: 0.3, 3: 0.2}, (2, 0.5, 0.5)),     # P(2) + P(3) exactly at theta2
    ({0: 0.3, 1: 0.4, 2: 0.2, 3: 0.1}, (1, 0.3, 0.5)),
    ({0: 0.9, 1: 0.05, 2: 0.03, 3: 0.02}, (0, 0.05, 0.5)),
])
def test_decision_rule(probs, expected):
    tier, probability, threshold = decide(probs, SafetyConfig(theta3=0.5, theta2=0.5))
    assert (tier, round(probability, 6), threshold) == expected
