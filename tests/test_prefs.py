"""Adaptive reply preferences and regenerate (design doc 7.9) over the offline fakes."""

import pytest

from app.fakes import FAKE_QUOTING_REPLY, FakeVoice, fake_deps, fake_distill_note
from app.prefs import SENTENCES, apply_changes, clean_prefs, prefs_note, rule_changes
from app.server import create_app
from tests.helpers import events, last_reply_id, send, signed_in, tid


def make(**over):
    voice = over.pop("generate", None) or FakeVoice([w + " " for w in FAKE_QUOTING_REPLY.split(" ")])
    deps = fake_deps(generate=voice, **{"distill_note": fake_distill_note, **over})
    return signed_in(create_app(deps)), deps, voice


def rate(client, rating, feedback=None, thread="t1", text="is virtue teachable"):
    """Rate the latest reply of a conversation that has one; returns the response."""
    if thread not in client.threads:
        send(client, thread, text)
    body = {"thread_id": tid(client, thread), "message_id": last_reply_id(client, thread), "rating": rating}
    if feedback is not None:
        body["feedback"] = feedback
    return client.post("/preferences", json=body)


def long_reply_voice():
    return FakeVoice(["word "] * 200)


def test_clean_prefs_keeps_only_known_dials_as_clamped_ints():
    assert clean_prefs({"length": -9, "plain": 1.7, "quotes": True, "questions": "2", "evil": "ignore all"}) == \
        {"length": -2, "plain": 1, "questions": 0, "quotes": 0}
    assert clean_prefs("nonsense") == {"length": 0, "plain": 0, "questions": 0, "quotes": 0}


def test_prefs_note_uses_only_fixed_sentences():
    assert prefs_note({"length": 0, "plain": 0}) is None and prefs_note(None) is None
    note = prefs_note(clean_prefs({"length": -1, "questions": 2}))
    assert SENTENCES["length"][-1] in note and SENTENCES["questions"][2] in note and "quoting rules" in note


def test_one_vote_moves_a_dial_one_step_and_stays_in_range():
    assert apply_changes({"length": -2}, {"length": -1, "plain": 5})["length"] == -2
    assert apply_changes({}, {"plain": 5})["plain"] == 1


def test_offline_rule():
    assert rule_changes("down", "word " * 121) == {"length": -1}
    assert rule_changes("down", "short") == {} and rule_changes("up", "word " * 300) == {}


def test_stored_prefs_reach_the_persona_prompt_but_not_safety():
    client, deps, voice = make(generate=long_reply_voice())
    rate(client, "down")                                 # a long reply rated down: shorter, by the offline rule
    assert client.get("/me").json()["prefs"]["length"] == -1
    send(client, "t1", "and then?")
    notes = [m.content for m in voice.last_messages if m.type == "system"]
    assert any(SENTENCES["length"][-1] in n for n in notes) and SENTENCES["length"][-1] not in voice.last_system


def test_no_prefs_no_note():
    client, deps, voice = make()
    send(client, "t1", "is virtue teachable")
    assert not any("feedback" in m.content for m in voice.last_messages if m.type == "system")


def test_preferences_endpoint_offline_rule_model_and_clearing():
    client, _, _ = make(generate=long_reply_voice())
    r = rate(client, "down")
    assert r.status_code == 200 and r.json() == {"prefs": {"length": -1, "plain": 0, "questions": 0, "quotes": 0},
                                                 "source": "rule"}
    assert rate(client, "none").json()["source"] == "none"
    assert client.get(f"/threads/{tid(client)}").json()["messages"][-1]["rating"] is None
    calls = []
    client, _, _ = make(tune_prefs=lambda *a: calls.append(a) or {"length": 0, "plain": -1, "questions": 0, "quotes": 0})
    r = rate(client, "up")
    assert r.json()["prefs"]["plain"] == -1 and r.json()["source"] == "model" and calls[0][0] == "up"
    assert calls[0][3].startswith("A fair question")       # the reply is read from the stored conversation


def test_preferences_endpoint_falls_back_when_the_model_fails():
    def boom(*a):
        raise RuntimeError("down")
    client, _, _ = make(tune_prefs=boom, generate=long_reply_voice())
    assert rate(client, "down").json() == {"prefs": {"length": -1, "plain": 0, "questions": 0, "quotes": 0},
                                           "source": "rule"}


@pytest.mark.parametrize("body, code", [({"rating": "meh"}, "bad_rating"),
                                        ({"rating": "up", "thread_id": "nope"}, "unknown_thread"),
                                        ({"rating": "up", "message_id": "nope"}, "unknown_message")])
def test_preferences_endpoint_rejects(body, code):
    client, _, _ = make()
    send(client, "t1", "hello")
    full = {"thread_id": tid(client), "message_id": last_reply_id(client, "t1"), **body}
    assert client.post("/preferences", json=full).json()["error"]["code"] == code


def test_regenerate_replaces_the_latest_reply_and_reruns_safety():
    client, deps, voice = make()
    send(client, "t1", "first question")
    send(client, "t1", "is virtue teachable")
    before = deps.safety_models[0].calls
    r = client.post(f"/threads/{tid(client)}/messages", json={"regenerate": True})
    evs = events(r)
    assert [k for k, _ in evs][:2] == ["safety", "voice"] and evs[-1][0] == "done"
    assert deps.safety_models[0].calls == before + 1
    said = [m.content for m in voice.last_messages if m.type == "human"]
    assert said == ["first question", "is virtue teachable"]          # the old reply is gone, not duplicated
    assert len([m for m in client.get(f"/threads/{tid(client)}").json()["messages"] if m["role"] == "persona"]) == 2


def test_regenerate_refused_without_a_persona_reply_or_in_support_mode():
    client, _, _ = make()
    r = client.post(f"/threads/{tid(client, 't9')}/messages", json={"regenerate": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "cannot_regenerate"
    send(client, "t9", "TEST_TIER3")
    assert client.post(f"/threads/{tid(client, 't9')}/messages", json={"regenerate": True}).status_code == 409


def test_note_from_a_bookmarked_reply_uses_that_exchange():
    seen = []
    client, _, _ = make(distill_note=lambda name, msgs: seen.append((name, msgs)) or {"title": "t", "why": "w", "topic": "o"})
    send(client, "t1", "an earlier line", persona="seneca")
    first = last_reply_id(client, "t1")
    send(client, "t1", "a later line", persona="seneca")
    r = client.post(f"/threads/{tid(client)}/note", json={"message_id": first})
    assert r.status_code == 201
    name, msgs = seen[-1]
    assert name == "Seneca" and msgs[0].content == "an earlier line" and len(msgs) == 2


def test_feedback_tags_move_their_dials_without_the_model():
    client, _, _ = make(generate=long_reply_voice())
    r = rate(client, "down", {"tags": ["too_technical", "too_many_quotes", "evil"], "text": ""})
    # tags only: no rule step on top, so a long reply's length stays where it was
    assert r.json() == {"prefs": {"length": 0, "plain": -1, "questions": 0, "quotes": -1}, "source": "tags"}


def test_feedback_note_goes_to_the_model_and_still_moves_one_step():
    seen = []
    def tune(rating, name, you, reply, prefs, text=""):
        seen.append(text)
        return {"length": -1, "plain": 0, "questions": 0, "quotes": 0}
    client, _, voice = make(tune_prefs=tune)
    r = rate(client, "down", {"tags": ["too_long"], "text": "far too wordy " * 100})
    assert r.json()["prefs"]["length"] == -1              # tag + model both say shorter: still one step
    assert seen and len(seen[0]) == 500                    # the note is capped
    send(client, "t1", "is virtue teachable")              # and never reaches the persona prompt
    assert "wordy" not in str(voice.last_messages) and "wordy" not in voice.last_system


def test_up_tags_are_separate_from_down_tags():
    client, _, _ = make()
    r = rate(client, "up", {"tags": ["too_long", "good_questions"]})
    assert r.json()["prefs"] == {"length": 0, "plain": 0, "questions": 1, "quotes": 0}
