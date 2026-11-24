"""Adaptive reply preferences and regenerate (design doc 7.9) over the offline fakes."""

import pytest
from starlette.testclient import TestClient

from app.fakes import FAKE_QUOTING_REPLY, FakeVoice, fake_deps, fake_distill_note
from app.prefs import SENTENCES, apply_changes, clean_prefs, prefs_note, rule_changes
from app.server import create_app
from tests.test_server import events, send


def make(**over):
    voice = FakeVoice([w + " " for w in FAKE_QUOTING_REPLY.split(" ")])
    deps = fake_deps(generate=voice, **{"distill_note": fake_distill_note, **over})
    return TestClient(create_app(deps)), deps, voice


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


def test_prefs_reach_the_persona_prompt_but_not_safety():
    client, deps, voice = make()
    r = client.post("/threads/t1/messages", json={"text": "is virtue teachable", "persona_id": "socrates",
                                                  "prefs": {"length": -1, "x": "inject"}})
    assert r.status_code == 200
    notes = [m.content for m in voice.last_messages if m.type == "system"]
    assert any(SENTENCES["length"][-1] in n for n in notes)
    assert "inject" not in str(voice.last_messages) and SENTENCES["length"][-1] not in voice.last_system


def test_no_prefs_no_note():
    client, deps, voice = make()
    send(client, "t1", "is virtue teachable")
    assert not any("feedback" in m.content for m in voice.last_messages if m.type == "system")


def test_preferences_endpoint_offline_rule_and_model():
    client, _, _ = make()
    long = "word " * 200
    r = client.post("/preferences", json={"rating": "down", "persona_id": "socrates", "reply": long,
                                          "user_text": "hi", "prefs": {"length": 0}})
    assert r.status_code == 200 and r.json() == {"prefs": {"length": -1, "plain": 0, "questions": 0, "quotes": 0},
                                                 "source": "rule"}
    calls = []
    client, _, _ = make(tune_prefs=lambda *a: calls.append(a) or {"length": 0, "plain": -1, "questions": 0, "quotes": 0})
    r = client.post("/preferences", json={"rating": "up", "persona_id": "socrates", "reply": "ok", "prefs": {}})
    assert r.json()["prefs"]["plain"] == -1 and r.json()["source"] == "model" and calls[0][0] == "up"


def test_preferences_endpoint_falls_back_when_the_model_fails():
    def boom(*a):
        raise RuntimeError("down")
    client, _, _ = make(tune_prefs=boom)
    r = client.post("/preferences", json={"rating": "down", "persona_id": "socrates", "reply": "word " * 130})
    assert r.json() == {"prefs": {"length": -1, "plain": 0, "questions": 0, "quotes": 0}, "source": "rule"}


@pytest.mark.parametrize("body, code", [({"rating": "meh", "persona_id": "socrates", "reply": "x"}, "bad_rating"),
                                        ({"rating": "up", "persona_id": "camus", "reply": "x"}, "unknown_persona"),
                                        ({"rating": "up", "persona_id": "socrates", "reply": " "}, "empty_reply")])
def test_preferences_endpoint_rejects(body, code):
    client, _, _ = make()
    assert client.post("/preferences", json=body).json()["error"]["code"] == code


def test_regenerate_replaces_the_latest_reply_and_reruns_safety():
    client, deps, voice = make()
    send(client, "t1", "first question")
    send(client, "t1", "is virtue teachable")
    before = deps.safety_models[0].calls
    r = client.post("/threads/t1/messages", json={"regenerate": True, "prefs": {"length": -2}})
    evs = events(r)
    assert [k for k, _ in evs][:2] == ["safety", "voice"] and evs[-1][0] == "done"
    assert deps.safety_models[0].calls == before + 1
    said = [m.content for m in voice.last_messages if m.type == "human"]
    assert said == ["first question", "is virtue teachable"]          # the old reply is gone, not duplicated
    assert any(SENTENCES["length"][-2] in m.content for m in voice.last_messages if m.type == "system")


def test_regenerate_refused_without_a_persona_reply_or_in_support_mode():
    client, _, _ = make()
    r = client.post("/threads/t9/messages", json={"regenerate": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "cannot_regenerate"
    send(client, "t9", "TEST_TIER3")
    assert client.post("/threads/t9/messages", json={"regenerate": True}).status_code == 409


def test_note_from_a_bookmarked_exchange():
    seen = []
    client, _, _ = make(distill_note=lambda name, msgs: seen.append((name, msgs)) or {"title": "t", "why": "w", "topic": "o"})
    send(client, "t1", "is virtue teachable")
    r = client.post("/threads/t1/note", json={"you": "an earlier line", "them": "an earlier reply", "persona_id": "seneca"})
    assert r.status_code == 200
    name, msgs = seen[-1]
    assert name == "Seneca" and [m.content for m in msgs] == ["an earlier line", "an earlier reply"]


def test_feedback_tags_move_their_dials_without_the_model():
    client, _, _ = make()
    r = client.post("/preferences", json={"rating": "down", "persona_id": "socrates", "reply": "word " * 200,
                                          "prefs": {"length": 0},
                                          "feedback": {"tags": ["too_technical", "too_many_quotes", "evil"], "text": ""}})
    # tags only: no rule step on top, so a long reply's length stays where it was
    assert r.json() == {"prefs": {"length": 0, "plain": -1, "questions": 0, "quotes": -1}, "source": "tags"}


def test_feedback_note_goes_to_the_model_and_still_moves_one_step():
    seen = []
    def tune(rating, name, you, reply, prefs, text=""):
        seen.append(text)
        return {"length": -1, "plain": 0, "questions": 0, "quotes": 0}
    client, _, voice = make(tune_prefs=tune)
    r = client.post("/preferences", json={"rating": "down", "persona_id": "socrates", "reply": "x",
                                          "feedback": {"tags": ["too_long"], "text": "far too wordy " * 100}})
    assert r.json()["prefs"]["length"] == -1              # tag + model both say shorter: still one step
    assert seen and len(seen[0]) == 500                    # the note is capped
    send(client, "t1", "is virtue teachable")              # and never reaches the persona prompt
    assert "wordy" not in str(voice.last_messages) and "wordy" not in voice.last_system


def test_up_tags_are_separate_from_down_tags():
    client, _, _ = make()
    r = client.post("/preferences", json={"rating": "up", "persona_id": "socrates", "reply": "x",
                                          "feedback": {"tags": ["too_long", "good_questions"]}})
    assert r.json()["prefs"] == {"length": 0, "plain": 0, "questions": 1, "quotes": 0}
