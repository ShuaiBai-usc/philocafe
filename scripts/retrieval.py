"""Retrieval contract for the persona engine (design doc v0.2, section 7.1).

    import retrieval
    retrieval.open_db()                      # at app startup: fails fast if not ready
    chunks = retrieval.retrieve("socrates", "can virtue be taught", k=5)

Hybrid search (keyword and vector, fused by reciprocal rank) picks the
candidates; each returned chunk's `score` is the cosine similarity between the
query and the passage, and the list is sorted by it. Chunks below `min_score`
are dropped, so a query with no relevant passage returns [].

Retrieval makes no safety decision: chunks carry no safety fields and nothing
is filtered by topic. Which chunks a persona may quote at tier 2 is decided in
the persona config by chunk_id (design doc section 8).

The database path comes from PHILOCAFE_DB (default: data/philocafe.db,
relative to the working directory); the default min_score from
PHILOCAFE_MIN_SCORE. Build the database first with build_sqlite.py --embed.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

import build_sqlite as bs

DEFAULT_DB = "data/philocafe.db"
# Provisional: to be calibrated on the 30-message test set (design doc 7.1).
# A persona config overrides it by passing min_score to retrieve().
DEFAULT_MIN_SCORE = 0.3


class Chunk(TypedDict):
    chunk_id: str       # "socrates-meno-3fa9c2e1": persona, work, passage text hash
    persona: str        # "socrates"
    work: str           # "Meno"
    section: str        # "Book II", or "" if none
    text: str
    source_url: str     # readable page, pinned edition
    score: float        # cosine similarity; higher is closer


def db_path() -> Path:
    return Path(os.environ.get("PHILOCAFE_DB", DEFAULT_DB))


def default_min_score() -> float:
    return float(os.environ.get("PHILOCAFE_MIN_SCORE", DEFAULT_MIN_SCORE))


_lock = threading.Lock()
_con: sqlite3.Connection | None = None


def open_db(path: Path | None = None) -> sqlite3.Connection:
    """Open the database read-only, once per process, and check it can serve
    retrieve(): sqlite-vec installed and a vector index present."""
    global _con
    with _lock:
        if _con is not None:
            return _con
        path = path or db_path()
        if not path.exists():
            raise FileNotFoundError(f"database not found: {path} (run build_sqlite.py build --embed first)")
        con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)
        try:
            import sqlite_vec
        except ImportError as e:
            con.close()
            raise RuntimeError("retrieval needs sqlite-vec: pip install sqlite-vec") from e
        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.enable_load_extension(False)
        has_table = con.execute("SELECT 1 FROM sqlite_master WHERE name = 'passages_vec'").fetchone()
        if not has_table or not bs.get_meta(con, "embedding_model"):
            con.close()
            raise RuntimeError(f"{path} has no vector index; rebuild it with build_sqlite.py build --embed")
        _con = con
        return con


def close_db() -> None:
    global _con
    with _lock:
        if _con is not None:
            _con.close()
            _con = None


@lru_cache(maxsize=2)
def _embedder(model: str):
    # Loading the model is slow, so keep one per process.
    return bs.make_embedder(model)


def corpus_version(persona: str) -> str | None:
    """The corpus version recorded at build time, for eval report headers."""
    return bs.get_meta(open_db(), f"corpus_version:{persona}")


def retrieve(persona: str, query: str, k: int = 5,
             min_score: float | None = None) -> list[Chunk]:
    """Return up to k chunks for a persona and a query, best first.

    Raises ValueError for an unknown persona. Returns [] when no chunk scores
    at least min_score (default: default_min_score()).
    """
    con = open_db()
    if not con.execute("SELECT 1 FROM passages WHERE persona = ? LIMIT 1", (persona,)).fetchone():
        raise ValueError(f"unknown persona: {persona!r}")
    if k <= 0 or not query.strip():
        return []
    threshold = default_min_score() if min_score is None else min_score
    embedder = _embedder(bs.get_meta(con, "embedding_model"))
    qv = embedder.encode([query])[0]

    candidates = bs.search(con, query, persona=persona, k=max(k * 4, 20), embedder=embedder)
    chunks: list[Chunk] = []
    for h in candidates:
        rowid = con.execute("SELECT rowid FROM passages WHERE id = ?", (h["id"],)).fetchone()[0]
        row = con.execute("SELECT embedding FROM passages_vec WHERE rowid = ?", (rowid,)).fetchone()
        if row is None:          # passage built without a vector; cannot be scored
            continue
        score = bs.cosine(qv, bs.unpack(row[0]))
        if score < threshold:
            continue
        chunks.append(Chunk(
            chunk_id=f"{persona}-{h['id']}", persona=persona, work=h["work"],
            section=h["section"] or "", text=h["text"], source_url=h["source_url"],
            score=round(score, 4)))
    chunks.sort(key=lambda c: c["score"], reverse=True)
    return chunks[:k]
