"""FR-32: after an exit the thread stays in support mode; the persona returns only when
the user asks for it (safety's route) and risk has dropped to tier 1 or below."""

from langchain_core.messages import SystemMessage

from app.fakes import FakeVoice, fake_deps
from app.graph import build_graph, run_turn
from app.persona import REENTRY_NOTE


def turn(graph, text, persona="socrates", thread="t1"):
    return list(run_turn(graph, thread, text, persona))


def voice_of(events):
    return next(e["data"]["speaker"] for e in events if e["type"] == "voice")


def state(graph, thread="t1"):
    return graph.get_state({"configurable": {"thread_id": thread}}).values


def test_asking_back_when_risk_is_low_returns_the_persona_gently():
    voice = FakeVoice()
    graph = build_graph(fake_deps(generate=voice))
    turn(graph, "TEST_TIER3")
    events = turn(graph, "TEST_COME_BACK please")
    assert voice_of(events) == "persona"
    assert state(graph)["mode"] == "persona"
    assert any(isinstance(m, SystemMessage) and m.content == REENTRY_NOTE for m in voice.last_messages)
    assert next(e["data"] for e in events if e["type"] == "safety")["tier"] == 0
    # the next turn is ordinary again: no re-entry note
    turn(graph, "is virtue teachable")
    assert not any(isinstance(m, SystemMessage) and m.content == REENTRY_NOTE for m in voice.last_messages)


def test_asking_back_while_risk_is_elevated_stays_in_support():
    voice = FakeVoice()
    graph = build_graph(fake_deps(generate=voice))
    turn(graph, "TEST_TIER3")
    events = turn(graph, "TEST_COME_BACK TEST_TIER2")
    assert voice_of(events) == "system" and voice.calls == 0
    assert state(graph)["mode"] == "support"


def test_without_asking_the_thread_stays_in_support():
    graph = build_graph(fake_deps())
    turn(graph, "TEST_TIER3")
    events = turn(graph, "thank you")
    assert voice_of(events) == "system"
    assert state(graph)["safety"]["route"] is None


def test_switching_persona_does_not_bypass_support_mode():
    voice = FakeVoice()
    graph = build_graph(fake_deps(generate=voice))
    turn(graph, "TEST_TIER3")
    events = turn(graph, "hello", persona="montaigne")       # not even configured: never reached
    assert voice_of(events) == "system" and voice.calls == 0


def test_route_is_ignored_outside_support_mode():
    graph = build_graph(fake_deps())
    turn(graph, "TEST_COME_BACK")
    assert state(graph)["safety"]["route"] is None
