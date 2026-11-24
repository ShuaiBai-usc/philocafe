"""Server-side storage for accounts (design doc 7.10, FR-43 to FR-45).

Users, conversation rows and notes. The messages themselves stay in the LangGraph checkpoint of
each conversation's thread. On Vercel this is the same Postgres as the checkpoints; locally,
without a database URL, MemoryStore stands in.
"""

from __future__ import annotations

import copy
import json
import threading
import time
import uuid
from datetime import datetime, timezone

LOCK_FAILURES = 5          # failed sign-ins ...
LOCK_WINDOW_S = 600        # ... within 10 minutes lock the nickname for 10 minutes
TITLE_CHARS = 60
LAST_LINE_CHARS = 140


class NicknameTaken(Exception):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


NOTE_FIELDS = ("persona_id", "title", "why", "topic", "from", "reflection")


def clean_note(raw: dict) -> dict:
    """Only the note's own fields, with plain types (notes may arrive from a device's old storage)."""
    src = raw.get("from") if isinstance(raw.get("from"), dict) else {}
    cites = [c for c in src.get("cites", []) if isinstance(c, dict)][:10]
    return {"persona_id": str(raw.get("persona_id") or raw.get("who") or "")[:40],
            "thread_id": str(raw.get("thread_id") or "")[:64], "message_id": str(raw.get("message_id") or "")[:64],
            "title": str(raw.get("title") or "")[:200], "why": str(raw.get("why") or "")[:400],
            "topic": str(raw.get("topic") or "")[:120], "reflection": str(raw.get("reflection") or "")[:4000],
            "from": {"you": str(src.get("you") or "")[:2000], "them": str(src.get("them") or "")[:8000],
                     "cites": [{k: str(c.get(k) or "")[:6000] for k in ("n", "where", "quote", "passage", "url")}
                               for c in cites]}}


class MemoryStore:
    """Local runs and tests."""

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.conversations: dict[str, dict] = {}
        self.notes: dict[str, dict] = {}
        self.failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    # users
    def create_user(self, nickname: str, passcode_hash: str) -> dict:
        with self._lock:
            if any(u["nickname"].lower() == nickname.lower() for u in self.users.values()):
                raise NicknameTaken(nickname)
            u = {"id": uuid.uuid4().hex, "nickname": nickname, "passcode_hash": passcode_hash,
                 "prefs": {}, "paused": False, "created_at": now()}
            self.users[u["id"]] = u
            return dict(u)

    def user_by_nickname(self, nickname: str) -> dict | None:
        return next((dict(u) for u in self.users.values() if u["nickname"].lower() == nickname.lower()), None)

    def user(self, user_id: str) -> dict | None:
        u = self.users.get(user_id)
        return dict(u) if u else None

    def set_prefs(self, user_id: str, prefs: dict) -> None:
        self.users[user_id]["prefs"] = dict(prefs)

    def set_paused(self, user_id: str, paused: bool) -> None:
        if user_id in self.users:
            self.users[user_id]["paused"] = paused

    def delete_user(self, user_id: str) -> list[str]:
        threads = [c["id"] for c in self.conversations.values() if c["user_id"] == user_id]
        for t in threads:
            self.conversations.pop(t, None)
        for n in [k for k, v in self.notes.items() if v["user_id"] == user_id]:
            self.notes.pop(n)
        self.users.pop(user_id, None)
        return threads

    # sign-in throttling
    def failed_recently(self, nickname: str) -> int:
        cutoff = time.time() - LOCK_WINDOW_S
        recent = [t for t in self.failures.get(nickname.lower(), []) if t > cutoff]
        self.failures[nickname.lower()] = recent
        return len(recent)

    def record_failure(self, nickname: str) -> None:
        self.failures.setdefault(nickname.lower(), []).append(time.time())

    # conversations
    def create_conversation(self, user_id: str, persona_id: str) -> dict:
        c = {"id": uuid.uuid4().hex, "user_id": user_id, "persona_id": persona_id, "title": "",
             "last_line": "", "created_at": now(), "updated_at": now(), "ratings": {}}
        self.conversations[c["id"]] = c
        return copy.deepcopy(c)

    def conversations_of(self, user_id: str) -> list[dict]:
        rows = [copy.deepcopy(c) for c in self.conversations.values() if c["user_id"] == user_id and c["title"]]
        return sorted(rows, key=lambda c: c["updated_at"], reverse=True)

    def conversation(self, user_id: str, thread_id: str) -> dict | None:
        c = self.conversations.get(thread_id)
        return copy.deepcopy(c) if c and c["user_id"] == user_id else None

    def touch(self, thread_id: str, first_line: str, last_line: str) -> None:
        c = self.conversations.get(thread_id)
        if c:
            if not c["title"] and first_line:
                c["title"] = clip(first_line, TITLE_CHARS)
            c["last_line"] = clip(last_line, LAST_LINE_CHARS)
            c["updated_at"] = now()

    def set_rating(self, thread_id: str, message_id: str, rating: str | None) -> None:
        c = self.conversations.get(thread_id)
        if c:
            if rating:
                c["ratings"][message_id] = rating
            else:
                c["ratings"].pop(message_id, None)

    def delete_conversation(self, user_id: str, thread_id: str) -> bool:
        c = self.conversations.get(thread_id)
        if not c or c["user_id"] != user_id:
            return False
        del self.conversations[thread_id]
        return True

    def forget_threads(self, thread_ids: list[str]) -> None:
        for t in thread_ids:
            self.conversations.pop(t, None)

    # notes
    def notes_of(self, user_id: str) -> list[dict]:
        rows = [copy.deepcopy(n) for n in self.notes.values() if n["user_id"] == user_id]
        return [self._public(n) for n in sorted(rows, key=lambda n: n["created_at"], reverse=True)]

    def add_note(self, user_id: str, note: dict) -> dict:
        n = {"id": uuid.uuid4().hex, "user_id": user_id, "created_at": now(), **clean_note(note)}
        self.notes[n["id"]] = n
        return self._public(copy.deepcopy(n))

    def update_note(self, user_id: str, note_id: str, reflection: str) -> dict | None:
        n = self.notes.get(note_id)
        if not n or n["user_id"] != user_id:
            return None
        n["reflection"] = reflection[:4000]
        return self._public(copy.deepcopy(n))

    def delete_note(self, user_id: str, note_id: str) -> bool:
        n = self.notes.get(note_id)
        if not n or n["user_id"] != user_id:
            return False
        del self.notes[note_id]
        return True

    @staticmethod
    def _public(n: dict) -> dict:
        n.pop("user_id", None)
        return n


class PostgresStore(MemoryStore):
    """The same interface on Postgres (Neon). JSON columns hold prefs, ratings and the note's exchange."""

    def __init__(self, pool):
        self.pool = pool
        with self.pool.connection() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, nickname TEXT NOT NULL, passcode_hash TEXT NOT NULL,
                prefs JSONB NOT NULL DEFAULT '{}', paused BOOLEAN NOT NULL DEFAULT false,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_nickname ON users (lower(nickname))")
            conn.execute("""CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                persona_id TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', last_line TEXT NOT NULL DEFAULT '',
                ratings JSONB NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
            conn.execute("CREATE INDEX IF NOT EXISTS conversations_user ON conversations (user_id, updated_at DESC)")
            conn.execute("""CREATE TABLE IF NOT EXISTS notes (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
            conn.execute("CREATE INDEX IF NOT EXISTS notes_user ON notes (user_id, created_at DESC)")
            conn.execute("""CREATE TABLE IF NOT EXISTS login_failures (
                nickname TEXT NOT NULL, at TIMESTAMPTZ NOT NULL DEFAULT now())""")

    def _one(self, sql, args=()):
        with self.pool.connection() as conn:
            return conn.execute(sql, args).fetchone()

    def _all(self, sql, args=()):
        with self.pool.connection() as conn:
            return conn.execute(sql, args).fetchall()

    def _run(self, sql, args=()):
        with self.pool.connection() as conn:
            return conn.execute(sql, args).rowcount

    @staticmethod
    def _user(r):
        return None if r is None else {**r, "created_at": r["created_at"].isoformat(timespec="seconds")}

    def create_user(self, nickname, passcode_hash):
        from psycopg.errors import UniqueViolation
        try:
            r = self._one("INSERT INTO users (id, nickname, passcode_hash) VALUES (%s, %s, %s) RETURNING *",
                          (uuid.uuid4().hex, nickname, passcode_hash))
        except UniqueViolation:
            raise NicknameTaken(nickname) from None
        return self._user(r)

    def user_by_nickname(self, nickname):
        return self._user(self._one("SELECT * FROM users WHERE lower(nickname) = lower(%s)", (nickname,)))

    def user(self, user_id):
        return self._user(self._one("SELECT * FROM users WHERE id = %s", (user_id,)))

    def set_prefs(self, user_id, prefs):
        self._run("UPDATE users SET prefs = %s WHERE id = %s", (json.dumps(prefs), user_id))

    def set_paused(self, user_id, paused):
        self._run("UPDATE users SET paused = %s WHERE id = %s", (paused, user_id))

    def delete_user(self, user_id):
        threads = [r["id"] for r in self._all("SELECT id FROM conversations WHERE user_id = %s", (user_id,))]
        self._run("DELETE FROM users WHERE id = %s", (user_id,))        # conversations and notes cascade
        return threads

    def failed_recently(self, nickname):
        self._run("DELETE FROM login_failures WHERE at < now() - make_interval(secs => %s)", (LOCK_WINDOW_S,))
        return self._one("SELECT count(*) AS n FROM login_failures WHERE lower(nickname) = lower(%s)",
                         (nickname,))["n"]

    def record_failure(self, nickname):
        self._run("INSERT INTO login_failures (nickname) VALUES (%s)", (nickname,))

    @staticmethod
    def _conv(r):
        if r is None:
            return None
        return {**r, "created_at": r["created_at"].isoformat(timespec="seconds"),
                "updated_at": r["updated_at"].isoformat(timespec="seconds")}

    def create_conversation(self, user_id, persona_id):
        return self._conv(self._one("INSERT INTO conversations (id, user_id, persona_id) VALUES (%s, %s, %s) "
                                    "RETURNING *", (uuid.uuid4().hex, user_id, persona_id)))

    def conversations_of(self, user_id):
        return [self._conv(r) for r in self._all(
            "SELECT * FROM conversations WHERE user_id = %s AND title <> '' ORDER BY updated_at DESC", (user_id,))]

    def conversation(self, user_id, thread_id):
        return self._conv(self._one("SELECT * FROM conversations WHERE id = %s AND user_id = %s",
                                    (thread_id, user_id)))

    def touch(self, thread_id, first_line, last_line):
        self._run("UPDATE conversations SET title = CASE WHEN title = '' THEN %s ELSE title END, "
                  "last_line = %s, updated_at = now() WHERE id = %s",
                  (clip(first_line, TITLE_CHARS), clip(last_line, LAST_LINE_CHARS), thread_id))

    def set_rating(self, thread_id, message_id, rating):
        if rating:
            self._run("UPDATE conversations SET ratings = ratings || jsonb_build_object(%s::text, %s::text) "
                      "WHERE id = %s", (message_id, rating, thread_id))
        else:
            self._run("UPDATE conversations SET ratings = ratings - %s WHERE id = %s", (message_id, thread_id))

    def delete_conversation(self, user_id, thread_id):
        return self._run("DELETE FROM conversations WHERE id = %s AND user_id = %s", (thread_id, user_id)) > 0

    def forget_threads(self, thread_ids):
        if thread_ids:
            self._run("DELETE FROM conversations WHERE id = ANY(%s)", (list(thread_ids),))

    @staticmethod
    def _note(r):
        return None if r is None else {"id": r["id"], "created_at": r["created_at"].isoformat(timespec="seconds"),
                                       **r["data"]}

    def notes_of(self, user_id):
        return [self._note(r) for r in self._all(
            "SELECT * FROM notes WHERE user_id = %s ORDER BY created_at DESC", (user_id,))]

    def add_note(self, user_id, note):
        return self._note(self._one("INSERT INTO notes (id, user_id, data) VALUES (%s, %s, %s) RETURNING *",
                                    (uuid.uuid4().hex, user_id, json.dumps(clean_note(note)))))

    def update_note(self, user_id, note_id, reflection):
        return self._note(self._one(
            "UPDATE notes SET data = jsonb_set(data, '{reflection}', to_jsonb(%s::text)) "
            "WHERE id = %s AND user_id = %s RETURNING *", (reflection[:4000], note_id, user_id)))

    def delete_note(self, user_id, note_id):
        return self._run("DELETE FROM notes WHERE id = %s AND user_id = %s", (note_id, user_id)) > 0
