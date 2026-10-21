"""The retrieval contract (design doc 7.1), owned by the data side.

The implementation lives in scripts/retrieval.py; the app imports it from here
so that no other module has to touch sys.path. Nothing is filtered or changed
on the way through.
"""

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def use_sqlite_with_extensions() -> None:
    """open_db() loads sqlite-vec, which needs a Python built with SQLite extension
    loading. Vercel's runtime Python is not (ADR-11), so there the pysqlite3-binary
    wheel (its own SQLite, with extension loading and FTS5) stands in for sqlite3.
    Must run before scripts/retrieval.py is imported."""
    import sqlite3
    if hasattr(sqlite3.Connection, "enable_load_extension"):
        return
    import pysqlite3          # installed on Linux x86_64 only (pyproject.toml)
    sys.modules["sqlite3"] = pysqlite3


use_sqlite_with_extensions()

from retrieval import Chunk, corpus_version, default_min_score, open_db, retrieve  # noqa: E402

__all__ = ["Chunk", "corpus_version", "default_min_score", "open_db", "retrieve"]
