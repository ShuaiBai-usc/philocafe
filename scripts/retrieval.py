"""Retrieval contract for the persona engine (design doc section 7.1).

    from retrieval import retrieve
    chunks = retrieve("socrates", "can virtue be taught", k=5)

Each chunk follows the `Chunk` contract, plus one extra field, `sensitive`,
listing flags such as "death" or "suicide" so the safety layer can treat
those passages with care. Pass `exclude_flags=("suicide",)` to drop them.

The database path comes from the PHILOCAFE_DB environment variable
(default: data/philocafe.db, relative to the working directory).
Build it first with build_sqlite.py.
"""

from __future__ import annotations

import os
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

import build_sqlite as bs

DEFAULT_DB = "data/philocafe.db"


class Chunk(TypedDict):
    chunk_id: str       # "socrates-meno-00012-00020": persona + passage id
    persona: str        # "socrates"
    work: str           # "Meno"
    section: str        # "Book IV" where the text has sections, else "turns 13-21"
    text: str
    source_url: str
    score: float        # hybrid rank score; higher is closer
    sensitive: list[str]  # extra field: "death", "suicide", "violence", "sexuality"


def db_path() -> Path:
    return Path(os.environ.get("PHILOCAFE_DB", DEFAULT_DB))


@lru_cache(maxsize=2)
def _embedder(model: str):
    # Loading the model is slow, so keep one per process.
    return bs.make_embedder(model)


def _open(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(f"database not found: {path} (run build_sqlite.py build first)")
    return bs.connect(path)


def _section(row_section: str, work: str, turn_start: int, turn_end: int) -> str:
    # Jowett's texts carry no Stephanus numbers. Where a work has no real
    # section (or only its subtitle, e.g. "Lysis Or, Friendship"), cite the
    # 1-based turn range, which is stable and can be looked up in turns.
    if row_section and not row_section.startswith(work):
        return row_section
    return f"turns {turn_start + 1}-{turn_end + 1}"


def retrieve(persona: str, query: str, k: int = 5,
             exclude_flags: tuple[str, ...] = ()) -> list[Chunk]:
    """Return the top-k chunks for a persona and a query.

    Raises ValueError for an unknown persona; returns [] when nothing matches.
    """
    con = _open(db_path())
    try:
        if not con.execute("SELECT 1 FROM passages WHERE persona = ? LIMIT 1", (persona,)).fetchone():
            raise ValueError(f"unknown persona: {persona!r}")
        if k <= 0 or not query.strip():
            return []
        model = bs.get_meta(con, "embedding_model")
        hits = bs.search(con, query, persona=persona, k=k, exclude_flags=tuple(exclude_flags),
                         embedder=_embedder(model) if model else None)
        chunks = []
        for h in hits:
            start, end = con.execute("SELECT turn_start, turn_end FROM passages WHERE id = ?",
                                     (h["id"],)).fetchone()
            chunks.append(Chunk(
                chunk_id=f"{persona}-{h['id']}", persona=persona, work=h["work"],
                section=_section(h["section"] or "", h["work"], start, end),
                text=h["text"], source_url=h["source_url"], score=h["score"],
                sensitive=h["sensitive"]))
        return chunks
    finally:
        con.close()
