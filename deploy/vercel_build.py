"""Vercel build step (pyproject.toml [tool.vercel.scripts] build; ADR-11).

Runs after the dependencies in requirements.txt are installed:
1. builds data/philocafe.db from data/processed/ with the vector index, downloading the
   embedding model into .cache/fastembed so the function can load it offline;
2. writes ui/web/index.html and copies the web app to public/, which Vercel serves from its CDN.

Run it locally to check a deployment build: .venv/bin/python deploy/vercel_build.py
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PERSONAS = ["socrates"]               # one corpus per persona config that ships


def run(*args: str) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True,
                   env={**os.environ, "FASTEMBED_CACHE_PATH": str(ROOT / ".cache" / "fastembed")})


def main() -> None:
    db = ROOT / "data" / "philocafe.db"
    db.unlink(missing_ok=True)
    for persona in PERSONAS:
        run("scripts/build_sqlite.py", "build", "--persona", persona,
            "--processed", f"data/processed/{persona}", "--db", str(db), "--embed")
    run("ui/web/tools/build_index.py")

    public = ROOT / "public"
    shutil.rmtree(public, ignore_errors=True)
    shutil.copytree(ROOT / "ui" / "web", public,
                    ignore=shutil.ignore_patterns("tools", "template.html", "data.json", "*.md"))
    print(f"public/: {sum(1 for _ in public.rglob('*') if _.is_file())} files")


if __name__ == "__main__":
    main()
