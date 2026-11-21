"""User-test submissions: conversations testers paste into ui/web/test.html.

Unlike the café itself (D8: nothing about a conversation is written on the server), these
are kept on purpose: the tester copies the chat, can edit it, and submits it for the class
research with the consent line shown under the Submit button. They are never purged by the
daily checkpoint purge. Nothing identifying is stored with them (no IP, no user agent, no
thread ID): only the philosopher, the pasted text, its turn count and the time.

On Vercel they go to the same Postgres as the checkpoints (table test_submissions); locally,
without a database URL, they stay in memory.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone

MAX_TRANSCRIPT = 20000
SEVERAL = "several"          # the "More than one" choice on the test page
_ME = re.compile(r"^\s*me\s*:", re.IGNORECASE | re.MULTILINE)


def count_turns(transcript: str) -> int:
    """A turn is one visitor message: a line that starts with "Me:" (the café's Copy chat format)."""
    return len(_ME.findall(transcript))


@dataclass
class Submission:
    id: int
    created_at: datetime
    persona: str
    turns: int
    transcript: str


def to_csv(rows: list[Submission]) -> str:
    """CSV with a BOM, so Excel and Numbers open the text as UTF-8."""
    out = io.StringIO()
    out.write("﻿")
    w = csv.writer(out)
    w.writerow(["id", "created_at", "persona", "turns", "transcript"])
    for r in rows:
        w.writerow([r.id, r.created_at.isoformat(timespec="seconds"), r.persona, r.turns, r.transcript])
    return out.getvalue()


class MemorySubmissions:
    """Local runs and tests."""

    def __init__(self):
        self.rows: list[Submission] = []

    def add(self, persona: str, transcript: str) -> int:
        row = Submission(len(self.rows) + 1, datetime.now(timezone.utc), persona, count_turns(transcript), transcript)
        self.rows.append(row)
        return row.id

    def all(self) -> list[Submission]:
        return list(self.rows)


class PostgresSubmissions:
    def __init__(self, pool):
        self.pool = pool
        with self.pool.connection() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS test_submissions (
                id BIGSERIAL PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                persona TEXT NOT NULL,
                turns INTEGER NOT NULL,
                transcript TEXT NOT NULL)""")

    def add(self, persona: str, transcript: str) -> int:
        with self.pool.connection() as conn:
            row = conn.execute("INSERT INTO test_submissions (persona, turns, transcript) VALUES (%s, %s, %s) "
                               "RETURNING id", (persona, count_turns(transcript), transcript)).fetchone()
        return row["id"]

    def all(self) -> list[Submission]:
        with self.pool.connection() as conn:
            rows = conn.execute("SELECT id, created_at, persona, turns, transcript FROM test_submissions "
                                "ORDER BY id").fetchall()
        return [Submission(**r) for r in rows]
