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

from retrieval import Chunk, corpus_version, default_min_score, open_db, retrieve  # noqa: E402

__all__ = ["Chunk", "corpus_version", "default_min_score", "open_db", "retrieve"]
