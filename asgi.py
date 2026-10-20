"""Vercel entrypoint (pyproject.toml [tool.vercel] entrypoint = "asgi:app"; ADR-11).

The build step (deploy/vercel_build.py) puts the corpus database in data/ and the
embedding model in .cache/fastembed; the function loads both read-only and offline.
"""

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
os.environ.setdefault("PHILOCAFE_DB", str(_ROOT / "data" / "philocafe.db"))
os.environ.setdefault("FASTEMBED_CACHE_PATH", str(_ROOT / ".cache" / "fastembed"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")       # the model ships in the bundle; never download at runtime

from app.server import create_app  # noqa: E402

app = create_app()
