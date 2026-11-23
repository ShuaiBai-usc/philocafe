"""User-test submissions (ui/web/test.html → POST /test/submissions, export as CSV)."""

import csv
import io

import pytest
from starlette.testclient import TestClient

from app.fakes import fake_deps
from app.server import WEB_DIR, create_app
from app.submissions import MAX_TRANSCRIPT, MemorySubmissions, count_turns

CHAT = "Philocafé · Seneca · 11/17/2026\n\nSeneca: Welcome. What weighs on you today?\n\nMe: I keep putting things off."


@pytest.fixture
def store():
    return MemorySubmissions()


@pytest.fixture
def client(store):
    # the access code is on: submissions must still go through without it
    return TestClient(create_app(fake_deps(), access_code="sesame", submissions=store))


def test_submit_without_the_access_code(client, store):
    r = client.post("/test/submissions", json={"persona": "seneca", "transcript": CHAT})
    assert r.status_code == 201 and r.json() == {"id": 1}
    (row,) = store.all()
    assert (row.persona, row.turns, row.transcript) == ("seneca", 1, CHAT)


def test_more_than_one_philosopher(client, store):
    body = {"personas": ["socrates", "seneca", "socrates"], "transcript": CHAT}
    assert client.post("/test/submissions", json=body).status_code == 201
    assert store.all()[0].persona == "socrates,seneca"


def test_page_cached_from_before_multi_select(client, store):
    assert client.post("/test/submissions", json={"persona": "several", "transcript": CHAT}).status_code == 201
    assert store.all()[0].persona == "several"


@pytest.mark.parametrize("body, code", [
    ({"persona": "camus", "transcript": CHAT}, "bad_persona"),
    ({"transcript": CHAT}, "bad_persona"),
    ({"personas": [], "transcript": CHAT}, "bad_persona"),
    ({"personas": ["seneca", "camus"], "transcript": CHAT}, "bad_persona"),
    ({"personas": "seneca", "transcript": CHAT}, "bad_persona"),
    ({"personas": ["several", "seneca"], "transcript": CHAT}, "bad_persona"),
    ({"persona": "seneca", "transcript": "   "}, "empty_transcript"),
    ({"persona": "seneca", "transcript": "x" * (MAX_TRANSCRIPT + 1)}, "transcript_too_long"),
    (["not", "an", "object"], "bad_json"),
])
def test_bad_submissions(client, store, body, code):
    r = client.post("/test/submissions", json=body)
    assert r.status_code == 400 and r.json()["error"]["code"] == code
    assert store.all() == []


def test_export_needs_the_admin_token(client, monkeypatch):
    monkeypatch.delenv("PHILOCAFE_ADMIN_TOKEN", raising=False)
    assert client.get("/test/submissions.csv").status_code == 401            # no token set: closed
    monkeypatch.setenv("PHILOCAFE_ADMIN_TOKEN", "t0ken")
    assert client.get("/test/submissions.csv").status_code == 401
    assert client.get("/test/submissions.csv", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_export_csv(client, monkeypatch):
    monkeypatch.setenv("PHILOCAFE_ADMIN_TOKEN", "t0ken")
    client.post("/test/submissions", json={"persona": "seneca", "transcript": CHAT})
    r = client.get("/test/submissions.csv", headers={"Authorization": "Bearer t0ken"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert len(rows) == 1 and rows[0]["persona"] == "seneca" and rows[0]["transcript"] == CHAT


def test_count_turns():
    assert count_turns(CHAT) == 1
    assert count_turns("Me: a\nSocrates: b\nme:  c\nSome me: d") == 2


def test_test_page_is_served(client):
    page = client.get("/test.html")
    assert page.status_code == 200 and "/test/submissions" in page.text
    for name in ("socrates", "seneca", "epictetus", "montaigne", "schopenhauer"):
        assert f"assets/mono_{name}.png" in page.text and (WEB_DIR / "assets" / f"mono_{name}.png").exists()
