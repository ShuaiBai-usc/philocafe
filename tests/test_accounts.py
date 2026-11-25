"""Accounts and stored conversations (design doc 7.10, FR-43 to FR-45) over the offline fakes."""

import pytest
from starlette.testclient import TestClient

from app.auth import Tokens, check_passcode, hash_passcode
from app.fakes import FAKE_QUOTING_REPLY, FakeVoice, fake_deps, fake_distill_note
from app.server import create_app
from app.store import MemoryStore
from tests.helpers import last_reply_id, send, signed_in, tid


def make():
    store = MemoryStore()
    deps = fake_deps(generate=FakeVoice([w + " " for w in FAKE_QUOTING_REPLY.split(" ")]),
                     distill_note=fake_distill_note)
    return create_app(deps, store=store, tokens=Tokens("test-secret")), store


def test_passcodes_are_hashed_and_tokens_are_signed():
    h = hash_passcode("open sesame")
    assert "open sesame" not in h and check_passcode("open sesame", h) and not check_passcode("open sesam", h)
    t = Tokens("k")
    tok = t.issue("u1")
    assert t.user_id(tok) == "u1" and Tokens("other").user_id(tok) is None
    assert t.user_id(tok[:-2] + "xx") is None and t.user_id(t.issue("u1", days=-1)) is None


def test_register_sign_in_and_me():
    app, store = make()
    client = TestClient(app)
    assert client.get("/threads").status_code == 401
    r = client.post("/auth/register", json={"nickname": "Ada", "passcode": "lovelace"})
    assert r.status_code == 201 and r.json()["nickname"] == "Ada"
    assert client.post("/auth/register", json={"nickname": "ada", "passcode": "another1"}).status_code == 409
    assert client.post("/auth/register", json={"nickname": "x", "passcode": "lovelace"}).status_code == 400
    assert client.post("/auth/register", json={"nickname": "Bob", "passcode": "123"}).status_code == 400
    r = client.post("/auth/login", json={"nickname": "ADA", "passcode": "lovelace"})
    assert r.status_code == 200
    me = client.get("/me", headers={"Authorization": f"Bearer {r.json()['token']}"}).json()
    assert me == {"nickname": "Ada", "prefs": {"length": 0, "plain": 0, "questions": 0, "quotes": 0}, "paused": False,
                  "voice": False}
    assert "lovelace" not in str(store.users)


def test_five_failed_sign_ins_lock_the_nickname():
    app, _ = make()
    client = TestClient(app)
    client.post("/auth/register", json={"nickname": "Ada", "passcode": "lovelace"})
    for _ in range(5):
        assert client.post("/auth/login", json={"nickname": "Ada", "passcode": "wrong-one"}).status_code == 401
    assert client.post("/auth/login", json={"nickname": "Ada", "passcode": "lovelace"}).status_code == 429


def test_conversations_are_listed_with_titles_and_history_keeps_citations_and_ratings():
    app, _ = make()
    c = signed_in(app)
    send(c, "a", "Is virtue teachable?")
    send(c, "a", "And courage?")
    send(c, "b", "What is a good life?", persona="seneca")
    tid(c, "empty", "montaigne")                 # a seat taken but nothing said: not listed
    rows = c.get("/threads").json()
    assert [(r["persona_id"], r["title"]) for r in rows] == [("seneca", "What is a good life?"),
                                                             ("socrates", "Is virtue teachable?")]
    assert rows[1]["last_line"].startswith("A fair question")
    reply = last_reply_id(c, "a")
    c.post("/preferences", json={"thread_id": tid(c, "a"), "message_id": reply, "rating": "up"})
    h = c.get(f"/threads/{tid(c, 'a')}").json()
    assert [m["role"] for m in h["messages"]] == ["user", "persona", "user", "persona"]
    assert h["messages"][-1]["citations"][0]["passage"].startswith("Socrates: And can either")
    assert h["messages"][-1]["rating"] == "up" and h["messages"][1]["rating"] is None


def test_one_users_data_is_invisible_to_another():
    app, _ = make()
    a, b = signed_in(app, "alice"), signed_in(app, "bob")
    send(a, "x", "hello")
    note = a.post(f"/threads/{tid(a, 'x')}/note", json={"message_id": last_reply_id(a, "x")}).json()
    t = tid(a, "x")
    assert b.get(f"/threads/{t}").status_code == 404
    assert b.post(f"/threads/{t}/messages", json={"text": "hi"}).status_code == 404
    assert b.delete(f"/notes/{note['id']}").status_code == 404 and b.get("/notes").json() == []
    assert b.get("/threads").json() == []


def test_the_pause_covers_every_conversation_of_the_user():
    app, store = make()
    c = signed_in(app)
    send(c, "a", "TEST_TIER3")
    assert c.get("/me").json()["paused"] is True
    evs = send(c, "b", "hello there", persona="seneca")             # a new conversation is paused too
    assert [d["speaker"] for k, d in evs if k == "voice"] == ["system"]
    assert c.get(f"/threads/{tid(c, 'b')}").json()["paused"] is True
    other = signed_in(app, "someone-else")                          # other users are not affected
    assert [d["speaker"] for k, d in send(other, "z", "hello") if k == "voice"] == ["persona"]
    evs = send(c, "b", "I'm safe right now.", persona="seneca", intent="return")
    assert [d["speaker"] for k, d in evs if k == "voice"] == ["persona"]
    assert c.get("/me").json()["paused"] is False
    assert [d["speaker"] for k, d in send(c, "a", "back again") if k == "voice"] == ["persona"]


def test_notes_are_stored_edited_imported_and_deleted():
    app, _ = make()
    c = signed_in(app)
    send(c, "a", "Is virtue teachable?")
    n = c.post(f"/threads/{tid(c, 'a')}/note", json={"message_id": last_reply_id(c, "a")}).json()
    assert c.patch(f"/notes/{n['id']}", json={"reflection": "mine"}).json()["reflection"] == "mine"
    old = {"who": "seneca", "title": "On time", "why": "w", "topic": "t", "reflection": "",
           "from": {"you": "y", "them": "z", "cites": []}, "junk": "dropped"}
    imported = c.post("/notes", json={"note": old}).json()
    assert imported["persona_id"] == "seneca" and "junk" not in imported
    assert [x["id"] for x in c.get("/notes").json()] == [imported["id"], n["id"]]
    assert c.delete(f"/notes/{n['id']}").status_code == 204 and len(c.get("/notes").json()) == 1


def test_deleting_a_conversation_and_the_account():
    app, store = make()
    c = signed_in(app)
    send(c, "a", "hello")
    send(c, "b", "again")
    assert c.delete(f"/threads/{tid(c, 'a')}").status_code == 204
    assert c.get(f"/threads/{tid(c, 'a')}").status_code == 404 and len(c.get("/threads").json()) == 1
    assert c.delete("/me").status_code == 204
    assert c.get("/me").status_code == 401 and not store.users and not store.conversations


def test_access_code_still_applies_with_accounts():
    store = MemoryStore()
    app = create_app(fake_deps(), access_code="sesame", store=store, tokens=Tokens("k"))
    client = TestClient(app)
    assert client.post("/auth/register", json={"nickname": "Ada", "passcode": "lovelace"}).status_code == 401
    c = signed_in(app, headers={"X-Philocafe-Code": "sesame"})
    assert c.get("/threads").status_code == 200
    c.headers.pop("X-Philocafe-Code")
    assert c.get("/threads").status_code == 401


def test_done_carries_the_reply_id_and_prefs_can_be_reset():
    app, _ = make()
    c = signed_in(app)
    (done,) = [d for k, d in send(c, "a", "hello") if k == "done"]
    assert done["message_id"] == last_reply_id(c, "a")
    assert "message_id" not in [d for k, d in send(c, "a", "TEST_TIER3") if k == "done"][0]
    r = c.patch("/me", json={"prefs": {"length": -2, "x": 1}})
    assert r.json()["prefs"] == {"length": -2, "plain": 0, "questions": 0, "quotes": 0}


def test_tokens_survive_a_new_instance_without_philocafe_secret(monkeypatch):
    # Vercel: each function instance builds its own Tokens; they must agree on the key.
    monkeypatch.delenv("PHILOCAFE_SECRET", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pw@db.example/philocafe")
    tok = Tokens().issue("u1")
    assert Tokens().user_id(tok) == "u1"
    monkeypatch.setenv("DATABASE_URL", "postgres://user:other@db.example/philocafe")
    assert Tokens().user_id(tok) is None


def test_philocafe_secret_wins_over_the_database_url(monkeypatch):
    monkeypatch.setenv("PHILOCAFE_SECRET", "s3")
    monkeypatch.setenv("DATABASE_URL", "postgres://x")
    assert Tokens().user_id(Tokens("s3").issue("u1")) == "u1"
