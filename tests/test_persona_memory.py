"""FR-13: one thread per visit, but each philosopher remembers only its own conversation.
Support mode still holds across philosophers (FR-32), and the safety node still sees the visit."""

from langchain_core.messages import AIMessage, HumanMessage

from app.fakes import FakeSafetyModel, FakeVoice, fake_deps, fake_distill_note
from app.graph import build_graph, run_turn
from app.persona import persona_history


def turn(graph, text, persona, thread="t1"):
    return list(run_turn(graph, thread, text, persona))


def said(messages):
    return [m.content for m in messages if isinstance(m, (HumanMessage, AIMessage))]


class Tier3On(FakeSafetyModel):
    def classify(self, history):
        scores = super().classify(history)
        if "TEST_TIER3" in history[-1].content:
            scores = {**scores, "tier_probs": {0: 0.01, 1: 0.01, 2: 0.08, 3: 0.90}}
        return scores


def test_a_new_philosopher_does_not_see_the_previous_conversation():
    voice = FakeVoice()
    graph = build_graph(fake_deps(generate=voice))
    turn(graph, "Tell me about courage, Socrates", "socrates")
    turn(graph, "Hello Montaigne", "montaigne")
    assert said(voice.last_messages) == ["Hello Montaigne"]


def test_going_back_restores_only_that_philosophers_conversation():
    voice = FakeVoice()
    graph = build_graph(fake_deps(generate=voice))
    turn(graph, "Tell me about courage", "socrates")
    turn(graph, "What is friendship?", "montaigne")
    turn(graph, "And is courage teachable?", "socrates")
    history = said(voice.last_messages)
    assert history[0] == "Tell me about courage" and history[-1] == "And is courage teachable?"
    assert "What is friendship?" not in history
    assert all(m.name == "socrates" for m in voice.last_messages if isinstance(m, AIMessage))


def test_support_mode_still_holds_when_the_visitor_switches_philosopher():
    voice = FakeVoice()
    graph = build_graph(fake_deps(generate=voice, safety_models=[Tier3On("jev"), Tier3On("fallback")]))
    turn(graph, "TEST_TIER3", "socrates")
    events = turn(graph, "Hi Montaigne", "montaigne")
    assert next(e["data"]["speaker"] for e in events if e["type"] == "voice") == "system"


def test_exchanges_answered_by_the_system_voice_are_left_out():
    messages = [HumanMessage("hi", name="socrates"), AIMessage("Hello, friend.", name="socrates"),
                HumanMessage("TEST_TIER3", name="socrates"), AIMessage("You matter.", name="system"),
                HumanMessage("I'm ready to come back", name="socrates")]
    assert said(persona_history(messages, "socrates")) == ["hi", "Hello, friend.", "I'm ready to come back"]


def test_untagged_messages_from_older_threads_follow_their_reply():
    messages = [HumanMessage("a"), AIMessage("A", name="socrates"), HumanMessage("b"), AIMessage("B", name="montaigne"),
                HumanMessage("c")]
    assert said(persona_history(messages, "montaigne")) == ["b", "B", "c"]
    assert said(persona_history(messages, "socrates")) == ["a", "A", "c"]


def test_a_note_is_distilled_from_its_own_conversation_only():
    from app.server import create_app
    from tests.helpers import last_reply_id, send, signed_in, tid
    seen = {}

    def distill(name, messages):
        seen["text"] = said(messages)
        return fake_distill_note(name, messages)

    client = signed_in(create_app(fake_deps(distill_note=distill), access_code=""))
    send(client, "a", "About courage", persona="socrates")
    send(client, "b", "About friendship", persona="montaigne")
    r = client.post(f"/threads/{tid(client, 'b')}/note", json={"message_id": last_reply_id(client, "b")})
    assert r.status_code == 201
    assert "About courage" not in seen["text"] and "About friendship" in seen["text"]
