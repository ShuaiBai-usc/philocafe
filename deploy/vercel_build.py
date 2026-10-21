"""Vercel build step (pyproject.toml [tool.vercel.scripts] build; ADR-11).

Runs after Vercel has installed the dependencies in pyproject.toml:
1. builds data/philocafe.db from data/processed/ with the vector index, downloading the
   embedding model into .cache/fastembed so the function can load it offline;
2. flattens that cache: Hugging Face stores the model behind chained symlinks, and the
   bundler copies every link's target, which put the 87 MB model in the bundle two or
   three times (526 MB, over Vercel's 500 MB limit). One real copy is enough to load it;
3. writes ui/web/index.html. app/server.py mounts ui/web with StaticFiles, which Vercel promotes
   to its CDN; the function serves the files itself otherwise.

Run it locally to check a deployment build: .venv/bin/python deploy/vercel_build.py
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "fastembed"
PERSONAS = ["socrates"]               # one corpus per persona config that ships


def run(*args: str) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True,
                   env={**os.environ, "FASTEMBED_CACHE_PATH": str(CACHE)})


def flatten_model_cache(cache: Path) -> None:
    """Replace the snapshot symlinks with real files and drop the blob stores, so the model
    is bundled once. fastembed still finds it offline through refs/ and snapshots/."""
    for link in cache.glob("models--*/snapshots/*/*"):
        if link.is_symlink():
            target = link.resolve()
            link.unlink()
            shutil.copy2(target, link)
    for blobs in [cache / "blobs", *cache.glob("models--*/blobs")]:
        shutil.rmtree(blobs, ignore_errors=True)
    shutil.rmtree(cache / ".locks", ignore_errors=True)
    links = [p for p in cache.rglob("*") if p.is_symlink()]
    assert not links, f"symlinks left in the model cache: {links[:3]}"
    size = sum(p.stat().st_size for p in cache.rglob("*") if p.is_file())
    print(f"model cache: {size / 1e6:.0f} MB, no symlinks", flush=True)


def main() -> None:
    db = ROOT / "data" / "philocafe.db"
    db.unlink(missing_ok=True)
    for persona in PERSONAS:
        run("scripts/build_sqlite.py", "build", "--persona", persona,
            "--processed", f"data/processed/{persona}", "--db", str(db), "--embed")
    flatten_model_cache(CACHE)
    run("ui/web/tools/build_index.py")


if __name__ == "__main__":
    main()
