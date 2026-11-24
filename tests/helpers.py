"""Signed-in test clients for the account-based API (design doc 7.10)."""

import json

from starlette.testclient import TestClient


def signed_in(app, nickname="tester", passcode="secret-pass", headers=None) -> TestClient:
    client = TestClient(app)
    if headers:
        client.headers.update(headers)
    r = client.post("/auth/register", json={"nickname": nickname, "passcode": passcode})
    assert r.status_code == 201, r.text
    client.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    client.threads = {}
    return client


def events(response):
    out = []
    for block in response.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def tid(client, name="t1", persona="socrates") -> str:
    """The real thread id behind a test's short name; creates the conversation on first use."""
    if name not in client.threads:
        r = client.post("/threads", json={"persona_id": persona})
        assert r.status_code == 201, r.text
        client.threads[name] = r.json()["thread_id"]
    return client.threads[name]


def send(client, thread, text, persona="socrates", **extra):
    r = client.post(f"/threads/{tid(client, thread, persona)}/messages", json={"text": text, **extra})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream"), r.text
    return events(r)


def last_reply_id(client, thread):
    msgs = client.get(f"/threads/{tid(client, thread)}").json()["messages"]
    return [m for m in msgs if m["role"] == "persona"][-1]["id"]
