"""Deployment settings (ADR-11): access code, Postgres checkpoints, cron purge, CDN-served web app.
No network and no database: Postgres itself is replaced where it would be opened."""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from starlette.testclient import TestClient

from app import server
from app.fakes import FAKE_QUOTING_REPLY, FakeVoice, fake_deps
from app.graph import build_graph, run_turn
from app.server import create_app


def quoting_deps():
    return fake_deps(generate=FakeVoice([w + " " for w in FAKE_QUOTING_REPLY.split(" ")]))


def test_access_code_guards_every_api_route():
    client = TestClient(create_app(quoting_deps(), access_code="sesame"))
    assert client.get("/personas").status_code == 401
    assert client.get("/personas").json()["error"]["code"] == "access_code"
    assert client.get("/personas", headers={"X-Philocafe-Code": "wrong"}).status_code == 401
    assert client.post("/threads").status_code == 401
    assert client.post("/threads/t1/messages", json={"text": "hi"}).status_code == 401
    assert client.post("/threads/t1/note").status_code == 401
    ok = {"X-Philocafe-Code": "sesame"}
    assert client.get("/personas", headers=ok).status_code == 200
    assert client.post("/threads/t1/messages", json={"text": "hi"}, headers=ok).status_code == 200


def test_no_access_code_means_open_locally(monkeypatch):
    monkeypatch.delenv("PHILOCAFE_ACCESS_CODE", raising=False)
    assert TestClient(create_app(quoting_deps())).get("/personas").status_code == 200


def test_purge_is_for_the_cron_only(monkeypatch):
    client = TestClient(create_app(quoting_deps()))
    monkeypatch.delenv("CRON_SECRET", raising=False)
    assert client.get("/internal/purge").status_code == 401
    monkeypatch.setenv("CRON_SECRET", "s3cret")
    assert client.get("/internal/purge", headers={"Authorization": "Bearer nope"}).status_code == 401
    r = client.get("/internal/purge", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200 and r.json()["deleted"] == 0       # in-memory checkpoints: nothing to purge


@pytest.mark.parametrize("env, expected", [
    ({}, None),
    ({"POSTGRES_URL": "postgres://p"}, "postgres://p"),
    ({"DATABASE_URL": "postgres://d", "POSTGRES_URL": "postgres://p"}, "postgres://d"),
    ({"PHILOCAFE_CHECKPOINT_URL": "postgres://x", "DATABASE_URL": "postgres://d"}, "postgres://x"),
])
def test_checkpoint_url_precedence(monkeypatch, env, expected):
    for name in ("PHILOCAFE_CHECKPOINT_URL", "DATABASE_URL", "POSTGRES_URL"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert server.checkpoint_url() == expected


def test_postgres_is_used_when_configured(monkeypatch):
    opened = []
    saver = InMemorySaver()
    monkeypatch.setattr(server, "postgres_checkpointer", lambda url: opened.append(url) or saver)
    monkeypatch.setenv("PHILOCAFE_CHECKPOINT_URL", "postgres://neon.example/db")
    client = TestClient(create_app(quoting_deps(), access_code=""))
    client.post("/threads/t1/messages", json={"text": "TEST_TIER3"})
    assert opened == ["postgres://neon.example/db"]
    # the support mode was written through the configured checkpointer
    assert saver.get_tuple({"configurable": {"thread_id": "t1"}}).checkpoint["channel_values"]["mode"] == "support"


def test_vercel_serves_the_web_app_from_the_cdn_not_the_function(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    assert TestClient(create_app(quoting_deps(), access_code="")).get("/").status_code == 404
    monkeypatch.delenv("VERCEL")
    assert TestClient(create_app(quoting_deps(), access_code="")).get("/").status_code == 200


def test_turn_state_survives_the_checkpoint_serializer():
    """What Postgres stores is LangGraph's serialized state; every field we rely on across
    turns must come back as it went in."""
    graph = build_graph(quoting_deps())
    for text in ("is virtue teachable", "TEST_TIER3"):
        list(run_turn(graph, "t1", text, "socrates"))
    state = graph.get_state({"configurable": {"thread_id": "t1"}}).values
    serde = JsonPlusSerializer()
    back = {k: serde.loads_typed(serde.dumps_typed(v)) for k, v in state.items()}
    assert back["mode"] == "support"
    assert [(type(m).__name__, m.name, m.content) for m in back["messages"]] == \
           [(type(m).__name__, m.name, m.content) for m in state["messages"]]
    assert back["safety"] == state["safety"]
    assert back["quotes"] == state["quotes"] and back["retrieved"] == state["retrieved"]


class PostgresLikeSaver(InMemorySaver):
    """In-memory checkpoints that the purge treats as the Postgres checkpointer."""
    conn = None


@pytest.mark.parametrize("setting, hours", [(None, 168.0), ("", 168.0), ("24", 24.0)])
def test_purge_deletes_conversations_older_than_the_retention_window(monkeypatch, setting, hours):
    asked = []
    monkeypatch.setattr(server, "stale_threads", lambda saver, h: asked.append(h) or ["old"])
    saver = PostgresLikeSaver()
    client = TestClient(create_app(quoting_deps(), checkpointer=saver, access_code=""))
    client.post("/threads/old/messages", json={"text": "hello"})
    monkeypatch.setenv("CRON_SECRET", "s3cret")
    if setting is not None:
        monkeypatch.setenv("PHILOCAFE_RETENTION_HOURS", setting)
    r = client.get("/internal/purge", headers={"Authorization": "Bearer s3cret"})
    assert asked == [hours] and r.json() == {"deleted": 1}
    assert saver.get_tuple({"configurable": {"thread_id": "old"}}) is None


def test_retention_zero_turns_the_purge_off(monkeypatch):
    monkeypatch.setattr(server, "stale_threads", lambda saver, h: pytest.fail("purge should be off"))
    saver = PostgresLikeSaver()
    client = TestClient(create_app(quoting_deps(), checkpointer=saver, access_code=""))
    client.post("/threads/kept/messages", json={"text": "hello"})
    monkeypatch.setenv("CRON_SECRET", "s3cret")
    monkeypatch.setenv("PHILOCAFE_RETENTION_HOURS", "0")
    r = client.get("/internal/purge", headers={"Authorization": "Bearer s3cret"})
    assert r.json()["deleted"] == 0 and "off" in r.json()["note"]
    assert saver.get_tuple({"configurable": {"thread_id": "kept"}}) is not None
