#!/usr/bin/env python3
"""Load a persona's processed JSONL files into one SQLite database.

All personas share one database file; each row carries a `persona` column,
and re-running for a persona replaces only that persona's rows.

Tables
  passages            RAG passages with citation metadata (rag_passages.jsonl)
  passage_flags       one row per (passage, sensitive flag), for filtering
  passages_fts        FTS5 full-text index over passages (keyword search, no deps)
  passages_vec        sqlite-vec vector index over passages (optional, --embed)
  turns               every speaker turn (turns.jsonl)
  sft_examples        chat-format examples (<persona>_sft.jsonl)
  meta                key/value settings, e.g. the embedding model used

Build (from the philocafe/ folder):
    python3 scripts/build_sqlite.py build --persona socrates \
        --processed data/processed/socrates --db data/philocafe.db --embed

Search:
    python3 scripts/build_sqlite.py search --db data/philocafe.db \
        --persona socrates --exclude suicide,death "is virtue teachable"

Keyword search needs only the standard library. Vector search needs
`pip install sqlite-vec fastembed` (sentence-transformers also works).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
import struct
import sys
from pathlib import Path

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS passages (
    rowid          INTEGER PRIMARY KEY,
    id             TEXT NOT NULL UNIQUE,
    persona        TEXT NOT NULL,
    author         TEXT,
    work           TEXT,
    translator     TEXT,
    section        TEXT,
    turn_start     INTEGER,
    turn_end       INTEGER,
    speakers       TEXT,        -- JSON array
    persona_words  INTEGER,     -- words spoken by the persona in this passage
    source_url     TEXT,
    text           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS passages_persona ON passages(persona);

CREATE TABLE IF NOT EXISTS passage_flags (
    passage_rowid  INTEGER NOT NULL REFERENCES passages(rowid) ON DELETE CASCADE,
    flag           TEXT NOT NULL,
    PRIMARY KEY (passage_rowid, flag)
);

CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(
    text, work, content='passages', content_rowid='rowid', tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS turns (
    persona      TEXT NOT NULL,
    work_id      TEXT NOT NULL,
    idx          INTEGER NOT NULL,
    author       TEXT,
    work         TEXT,
    section      TEXT,
    speaker      TEXT,
    kind         TEXT,          -- speech | narration
    attribution  TEXT,          -- explicit | tagged | inferred | narration
    words        INTEGER,
    source_url   TEXT,
    text         TEXT NOT NULL,
    PRIMARY KEY (persona, work_id, idx)
);
CREATE INDEX IF NOT EXISTS turns_speaker ON turns(persona, speaker);

CREATE TABLE IF NOT EXISTS sft_examples (
    id           INTEGER PRIMARY KEY,
    persona      TEXT NOT NULL,
    work_id      TEXT,
    work         TEXT,
    turn_idx     INTEGER,
    attribution  TEXT,
    is_question  INTEGER,
    messages     TEXT NOT NULL  -- JSON array of {role, content}
);
CREATE INDEX IF NOT EXISTS sft_persona ON sft_examples(persona);
"""


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


# --------------------------------------------------------------------------
# Embeddings
# --------------------------------------------------------------------------


class Embedder:
    name: str
    dim: int

    def encode(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class FastEmbedEmbedder(Embedder):
    """ONNX runtime embeddings via fastembed; no PyTorch needed."""

    def __init__(self, model: str):
        from fastembed import TextEmbedding
        self.model = TextEmbedding(model_name=model)
        self.name = model
        self.dim = len(next(iter(self.model.embed(["dimension probe"]))))

    def encode(self, texts):
        out = []
        for v in self.model.embed(texts, batch_size=32):
            v = [float(x) for x in v]
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


class SentenceTransformerEmbedder(Embedder):
    def __init__(self, model: str):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model)
        self.name = model
        self.dim = self.model.get_sentence_embedding_dimension()

    def encode(self, texts):
        return self.model.encode(texts, batch_size=32, normalize_embeddings=True,
                                 show_progress_bar=len(texts) > 100).tolist()


class HashEmbedder(Embedder):
    """Bag-of-words feature hashing. Not semantic; only for tests and offline runs."""

    def __init__(self, dim: int = 256):
        self.name, self.dim = f"hash-{dim}", dim

    def encode(self, texts):
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for w in re.findall(r"[a-z]+", t.lower()):
                h = int.from_bytes(hashlib.md5(w.encode()).digest()[:4], "little")
                v[h % self.dim] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


def make_embedder(model: str) -> Embedder:
    """Prefer fastembed (no PyTorch); fall back to sentence-transformers."""
    if model.startswith("hash"):
        return HashEmbedder()
    try:
        import fastembed  # noqa: F401
    except ImportError:
        try:
            return SentenceTransformerEmbedder(model)
        except ImportError:
            sys.exit("vector search needs an embedding library: pip install fastembed")
    return FastEmbedEmbedder(model)


def pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{len(blob) // 4}f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def corpus_version(rows: list[dict]) -> str:
    """Hash of a persona's passages (ids and text), recorded at build time so
    eval runs can name the exact corpus they used."""
    h = hashlib.sha256()
    for p in sorted(rows, key=lambda p: p["id"]):
        h.update(p["id"].encode("utf-8") + b"\0" + p["text"].encode("utf-8") + b"\0")
    return h.hexdigest()[:12]


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------


def connect(db: Path, need_vec: bool = False) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.execute("PRAGMA foreign_keys = ON")
    try:
        import sqlite_vec
        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.enable_load_extension(False)
    except ImportError:
        if need_vec:
            sys.exit("vector search needs: pip install sqlite-vec")
    con.executescript(SCHEMA)
    return con


def get_meta(con, key):
    row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def delete_persona(con: sqlite3.Connection, persona: str, has_vec: bool):
    rowids = [r[0] for r in con.execute("SELECT rowid FROM passages WHERE persona = ?", (persona,))]
    for rid in rowids:
        con.execute("INSERT INTO passages_fts(passages_fts, rowid, text, work) "
                    "SELECT 'delete', rowid, text, work FROM passages WHERE rowid = ?", (rid,))
        if has_vec:
            con.execute("DELETE FROM passages_vec WHERE rowid = ?", (rid,))
    con.execute("DELETE FROM passages WHERE persona = ?", (persona,))
    con.execute("DELETE FROM turns WHERE persona = ?", (persona,))
    con.execute("DELETE FROM sft_examples WHERE persona = ?", (persona,))


def build(args) -> int:
    persona = args.persona
    src: Path = args.processed
    con = connect(args.db, need_vec=args.embed)

    embedder = None
    if args.embed:
        stored = get_meta(con, "embedding_model")
        model = args.model or stored or DEFAULT_MODEL
        embedder = make_embedder(model)
        if stored and stored != embedder.name:
            sys.exit(f"database already uses embedding model {stored!r}; "
                     f"pass --model {stored} or start a new database")
        con.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS passages_vec "
                    f"USING vec0(embedding float[{embedder.dim}] distance_metric=cosine)")
        con.execute("INSERT OR REPLACE INTO meta VALUES ('embedding_model', ?)", (embedder.name,))
        con.execute("INSERT OR REPLACE INTO meta VALUES ('embedding_dim', ?)", (str(embedder.dim),))
    has_vec = get_meta(con, "embedding_model") is not None

    with con:
        delete_persona(con, persona, has_vec)

        rows = list(read_jsonl(src / "rag_passages.jsonl"))
        for p in rows:
            cur = con.execute(
                "INSERT INTO passages (id, persona, author, work, translator, section, turn_start,"
                " turn_end, speakers, persona_words, source_url, text)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (p["id"], persona, p["author"], p["work"], p["translator"], p["section"],
                 p["turn_range"][0], p["turn_range"][1], json.dumps(p["speakers"]),
                 p.get(f"{persona}_words", 0), p["source_url"], p["text"]))
            rid = cur.lastrowid
            p["_rowid"] = rid
            con.execute("INSERT INTO passages_fts(rowid, text, work) VALUES (?,?,?)",
                        (rid, p["text"], p["work"]))
            con.executemany("INSERT INTO passage_flags VALUES (?,?)",
                            [(rid, f) for f in p.get("sensitive", [])])

        con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                    (f"corpus_version:{persona}", corpus_version(rows)))

        if embedder:
            for i in range(0, len(rows), 256):
                batch = rows[i:i + 256]
                vecs = embedder.encode([p["text"] for p in batch])
                con.executemany("INSERT INTO passages_vec(rowid, embedding) VALUES (?,?)",
                                [(p["_rowid"], pack(v)) for p, v in zip(batch, vecs)])
        elif has_vec:
            print("[warn] this database has a vector index but --embed was not given; "
                  f"{persona} passages will be missing from vector search", file=sys.stderr)

        n_turns = 0
        for t in read_jsonl(src / "turns.jsonl"):
            con.execute(
                "INSERT INTO turns VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (persona, t["work_id"], t["idx"], t["author"], t["work"], t["section"],
                 t["speaker"], t["kind"], t["attribution"], t["words"], t["source_url"], t["text"]))
            n_turns += 1

        n_sft = 0
        sft_path = src / f"{persona}_sft.jsonl"
        if sft_path.exists():
            for e in read_jsonl(sft_path):
                m = e["meta"]
                con.execute(
                    "INSERT INTO sft_examples (persona, work_id, work, turn_idx, attribution,"
                    " is_question, messages) VALUES (?,?,?,?,?,?,?)",
                    (persona, m["work_id"], m["work"], m["turn_idx"], m["attribution"],
                     int(m["is_question"]), json.dumps(e["messages"], ensure_ascii=False)))
                n_sft += 1

    print(f"{persona}: passages={len(rows)} turns={n_turns} sft={n_sft} "
          f"corpus_version={get_meta(con, 'corpus_version:' + persona)} "
          f"vectors={'yes (' + get_meta(con, 'embedding_model') + ')' if embedder else 'no'} -> {args.db}")
    con.close()
    return 0


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------


def fts_query(text: str) -> str:
    # Quote each word so user input cannot break FTS5 syntax; OR them for recall.
    words = re.findall(r"\w+", text)
    return " OR ".join(f'"{w}"' for w in words) or '""'


def search(con: sqlite3.Connection, query: str, persona: str | None = None, k: int = 5,
           exclude_flags: tuple[str, ...] = (), mode: str = "hybrid",
           embedder: Embedder | None = None) -> list[dict]:
    """Return the top-k passages. mode: keyword | vector | hybrid (reciprocal rank fusion)."""
    where, params = [], []
    if persona:
        where.append("p.persona = ?")
        params.append(persona)
    if exclude_flags:
        where.append(f"p.rowid NOT IN (SELECT passage_rowid FROM passage_flags "
                     f"WHERE flag IN ({','.join('?' * len(exclude_flags))}))")
        params.extend(exclude_flags)
    filt = (" AND " + " AND ".join(where)) if where else ""
    pool = max(k * 4, 20)
    ranked: dict[str, list[int]] = {}

    if mode in ("keyword", "hybrid"):
        rows = con.execute(
            f"SELECT p.rowid FROM passages_fts f JOIN passages p ON p.rowid = f.rowid "
            f"WHERE passages_fts MATCH ?{filt} ORDER BY bm25(passages_fts) LIMIT ?",
            (fts_query(query), *params, pool)).fetchall()
        ranked["keyword"] = [r[0] for r in rows]

    if mode in ("vector", "hybrid") and get_meta(con, "embedding_model"):
        embedder = embedder or make_embedder(get_meta(con, "embedding_model"))
        qv = pack(embedder.encode([query])[0])
        # vec0 applies k before outer filters, so over-fetch and filter after.
        rows = con.execute(
            f"SELECT p.rowid FROM (SELECT rowid, distance FROM passages_vec "
            f"WHERE embedding MATCH ? AND k = ?) v JOIN passages p ON p.rowid = v.rowid "
            f"WHERE 1=1{filt} ORDER BY v.distance LIMIT ?",
            (qv, pool * 10, *params, pool)).fetchall()
        ranked["vector"] = [r[0] for r in rows]

    scores: dict[int, float] = {}
    for lst in ranked.values():
        for rank, rid in enumerate(lst):
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (60 + rank)
    top = sorted(scores, key=scores.get, reverse=True)[:k]

    out = []
    for rid in top:
        r = con.execute("SELECT id, persona, author, work, section, source_url, text "
                        "FROM passages WHERE rowid = ?", (rid,)).fetchone()
        flags = [f[0] for f in con.execute(
            "SELECT flag FROM passage_flags WHERE passage_rowid = ?", (rid,))]
        out.append(dict(id=r[0], persona=r[1], author=r[2], work=r[3], section=r[4],
                        source_url=r[5], text=r[6], sensitive=flags, score=round(scores[rid], 4)))
    return out


def cmd_search(args) -> int:
    con = connect(args.db, need_vec=args.mode == "vector")
    for hit in search(con, args.query, args.persona, args.k, tuple(f for f in args.exclude.split(",") if f), args.mode):
        print(f"[{hit['id']}] {hit['author']}, {hit['work']} {hit['section']} "
              f"score={hit['score']} sensitive={hit['sensitive']}")
        print("   " + hit["text"][:300].replace("\n", "\n   ") + "\n")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="load a persona's JSONL files")
    b.add_argument("--persona", required=True)
    b.add_argument("--processed", type=Path, required=True, help="folder with the JSONL files")
    b.add_argument("--db", type=Path, default=Path("data/philocafe.db"))
    b.add_argument("--embed", action="store_true", help="also build the vector index")
    b.add_argument("--model", help=f"embedding model (default {DEFAULT_MODEL}; 'hash' for offline tests)")
    b.set_defaults(func=build)

    s = sub.add_parser("search", help="search passages")
    s.add_argument("query")
    s.add_argument("--db", type=Path, default=Path("data/philocafe.db"))
    s.add_argument("--persona")
    s.add_argument("-k", type=int, default=5)
    s.add_argument("--exclude", default="", help="comma-separated sensitive flags to filter out, e.g. suicide,death")
    s.add_argument("--mode", choices=["keyword", "vector", "hybrid"], default="hybrid")
    s.set_defaults(func=cmd_search)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
