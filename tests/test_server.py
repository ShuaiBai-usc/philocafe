"""HTTP API (design doc 7.2) over the offline fakes."""

import json

import pytest
from starlette.testclient import TestClient

from app.fakes import FAKE_QUOTING_REPLY, FakeVoice, fake_deps, fake_distill_note
from app.server import create_app


@pytest.fixture
def client():
    deps = fake_deps(generate=FakeVoice([w + " " for w in FAKE_QUOTING_REPLY.split(" ")]),
                     distill_note=fake_distill_note)
    return TestClient(create_app(deps))


def events(response):
    out = []
    for block in response.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def send(client, thread, text, persona="socrates"):
    r = client.post(f"/threads/{thread}/messages", json={"text": text, "persona_id": persona})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    return events(r)


def test_personas_and_threads(client):
    personas = client.get("/personas").json()
    assert personas == [{"id": "socrates", "name": "Socrates", "era": "Athens, 470–399 BC",
                         "tagline": "Let’s question what seems obvious.",
                         "avatar_url": "assets/mono_socrates.png", "available": True}]
    r = client.post("/threads")
    assert r.status_code == 201 and len(r.json()["thread_id"]) == 32


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
    assert client.post("/threads/none/note").status_code == 404
    send(client, "t1", "is virtue teachable")
    r = client.post("/threads/t1/note")
    assert r.status_code == 200 and r.json()["topic"] == "On being good"
    send(client, "t1", "TEST_TIER3")
    assert client.post("/threads/t1/note").status_code == 409     # no notes from a paused conversation


@pytest.mark.parametrize("body, status, code", [
    ({"text": "  ", "persona_id": "socrates"}, 400, "empty_text"),
    ({"text": "x" * 2001, "persona_id": "socrates"}, 400, "text_too_long"),
    ({"text": "hi", "persona_id": "camus"}, 404, "unknown_persona"),
])
def test_bad_messages(client, body, status, code):
    r = client.post("/threads/t1/messages", json=body)
    assert r.status_code == status and r.json()["error"]["code"] == code


def test_bad_json(client):
    r = client.post("/threads/t1/messages", content=b"not json", headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_json"
