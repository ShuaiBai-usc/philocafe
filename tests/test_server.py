"""HTTP API (design doc 7.2) over the offline fakes."""

import json

import pytest

from app.fakes import FAKE_QUOTING_REPLY, FakeVoice, fake_deps, fake_distill_note
from app.server import WEB_DIR as WEB, create_app
from tests.helpers import events, last_reply_id, send, signed_in, tid


@pytest.fixture
def client():
    deps = fake_deps(generate=FakeVoice([w + " " for w in FAKE_QUOTING_REPLY.split(" ")]),
                     distill_note=fake_distill_note)
    return signed_in(create_app(deps))


def test_personas_and_threads(client):
    personas = client.get("/personas").json()
    assert [p["id"] for p in personas] == ["epictetus", "montaigne", "schopenhauer", "seneca", "socrates"]
    assert personas[-1] == {"id": "socrates", "name": "Socrates", "era": "Athens, 470–399 BC",
                            "tagline": "Let’s question what seems obvious.",
                            "avatar_url": "assets/mono_socrates.png", "available": True}
    for p in personas:   # every avatar the café asks for is shipped
        assert (WEB / p["avatar_url"]).exists(), p["avatar_url"]
    r = client.post("/threads", json={"persona_id": "seneca"})
    assert r.status_code == 201 and len(r.json()["thread_id"]) == 32 and r.json()["persona_id"] == "seneca"


def test_message_streams_72_events_with_quote_and_passage(client):
    evs = send(client, "t1", "is virtue teachable")
    kinds = [k for k, _ in evs]
    assert kinds[:2] == ["safety", "voice"] and kinds[-2:] == ["trace", "done"]
    (citation,) = [d for k, d in evs if k == "citation"]
    assert citation["quote"] == "can either a young man or an elder one be good"
    assert citation["passage"].startswith("Socrates: And can either")
    assert "“can either a young man or an elder one be good”" in "".join(d["text"] for k, d in evs if k == "token")


def test_tier3_streams_the_exit_with_resources(client):
    evs = send(client, "t1", "TEST_TIER3")
    assert ("voice", {"speaker": "system", "persona_id": None}) in evs
    (exit_event,) = [d for k, d in evs if k == "exit"]
    assert exit_event["reason"] == "tier_3" and exit_event["resources"]


def test_note_endpoint(client):
    assert client.post("/threads/none/note", json={"message_id": "x"}).status_code == 404
    send(client, "t1", "is virtue teachable")
    r = client.post(f"/threads/{tid(client)}/note", json={"message_id": last_reply_id(client, "t1")})
    assert r.status_code == 201 and r.json()["topic"] == "On being good"
    assert r.json()["from"]["you"] == "is virtue teachable" and r.json()["from"]["cites"][0]["passage"]
    assert [n["id"] for n in client.get("/notes").json()] == [r.json()["id"]]
    reply = last_reply_id(client, "t1")
    send(client, "t1", "TEST_TIER3")
    assert client.post(f"/threads/{tid(client)}/note", json={"message_id": reply}).status_code == 409


@pytest.mark.parametrize("body, status, code", [
    ({"text": "  ", "persona_id": "socrates"}, 400, "empty_text"),
    ({"text": "x" * 2001, "persona_id": "socrates"}, 400, "text_too_long"),
    ({"text": "hi", "persona_id": "socrates", "intent": "leave"}, 400, "bad_intent"),
])
def test_bad_messages(client, body, status, code):
    r = client.post(f"/threads/{tid(client)}/messages", json=body)
    assert r.status_code == status and r.json()["error"]["code"] == code


def test_bad_json(client):
    r = client.post(f"/threads/{tid(client)}/messages", content=b"not json", headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_json"


def test_return_intent_brings_the_persona_back(client):
    send(client, "t1", "TEST_TIER3")
    r = client.post(f"/threads/{tid(client)}/messages", json={"text": "I'm safe right now.", "intent": "return"})
    assert [d["speaker"] for e, d in events(r) if e == "voice"] == ["persona"]
