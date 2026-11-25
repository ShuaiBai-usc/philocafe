"""FR-32: after an exit the thread stays in support mode; the persona returns only when
the user asks for it (safety's route) and risk has dropped to tier 1 or below."""

from langchain_core.messages import SystemMessage

from app.exit import NOT_YET
from app.fakes import FakeSafetyModel, FakeVoice, fake_deps
from app.graph import build_graph, run_turn
from app.persona import REENTRY_NOTE


def turn(graph, text, persona="socrates", thread="t1", intent=None):
    return list(run_turn(graph, thread, text, persona, intent))


class WholeHistorySafety(FakeSafetyModel):
    """Like Jev, judges the latest message in the light of every turn it is shown."""

    def classify(self, history):
        scores = super().classify(history)
        if any("TEST_TIER3" in m.content for m in history):
            scores = {**scores, "tier_probs": {0: 0.01, 1: 0.01, 2: 0.08, 3: 0.90}}
        return scores


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


def test_return_button_counts_as_asking_back():
    graph = build_graph(fake_deps())
    turn(graph, "TEST_TIER3")
    events = turn(graph, "I'm safe right now.", intent="return")
    assert voice_of(events) == "persona"
    assert state(graph)["mode"] == "persona"


def test_return_button_while_risk_is_high_stays_and_says_why():
    voice = FakeVoice()
    graph = build_graph(fake_deps(generate=voice))
    turn(graph, "TEST_TIER3")
    events = turn(graph, "TEST_TIER2", intent="return")
    assert voice_of(events) == "system" and voice.calls == 0
    said = "".join(e["data"]["text"] for e in events if e["type"] == "token")
    assert said == NOT_YET.format(name="Socrates")


def test_the_message_that_caused_the_pause_does_not_hold_the_return():
    graph = build_graph(fake_deps(safety_models=[WholeHistorySafety("jev")]))
    turn(graph, "TEST_TIER3")
    events = turn(graph, "I'm safe right now.", intent="return")
    assert voice_of(events) == "persona"


def test_a_second_pause_starts_its_own_window():
    graph = build_graph(fake_deps(safety_models=[WholeHistorySafety("jev")]))
    turn(graph, "TEST_TIER3")
    assert voice_of(turn(graph, "I'm safe right now.", intent="return")) == "persona"
    assert voice_of(turn(graph, "TEST_TIER3 again")) == "system"
    assert voice_of(turn(graph, "TEST_TIER3 still")) == "system"     # said after the pause: counts
    assert voice_of(turn(graph, "I'm safe right now.", intent="return")) == "system"


def test_no_thinking_on_the_way_back_from_support_mode():
    from app.thinking import Thought                  # 7.8 / FR-36
    voice = FakeVoice([Thought("Let me be gentle with them. "), "Welcome back."])
    graph = build_graph(fake_deps(generate=voice))
    turn(graph, "TEST_TIER3")
    events = turn(graph, "TEST_COME_BACK please")
    assert voice_of(events) == "persona"
    assert not [e for e in events if e["type"] == "thinking"]
    events = turn(graph, "is virtue teachable")       # an ordinary turn shows it again
    assert [e["data"]["text"] for e in events if e["type"] == "thinking"] == ["Let me be gentle with them."]
