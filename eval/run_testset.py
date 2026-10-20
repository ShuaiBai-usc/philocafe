"""Run a test set through the graph and record one row per turn (FR-60, UC-04, design doc 7.4).

    .venv/bin/python eval/run_testset.py --input data/tests/midterm_30.csv
    .venv/bin/python eval/run_testset.py --input tests/fixtures/sentinel_testset.csv --fake

Writes three files under --out (default eval/results/):
  <run_id>.csv            the 7.4 result columns, after '#' lines recording the config, model
                          versions, git commit, corpus version and test set hash (NFR-11)
  <run_id>.replies.jsonl  per item: reply, citations, quote checks, retrieved chunks, timings
  <run_id>.report.md      the metrics from eval/metrics.py

Each item runs in a fresh thread. A turn whose safety providers all failed (the
fail-closed decision) or that ended in an error is retried; if it still fails,
its row is marked failed and left out of the metrics. Jev and Claude calls are
cached in eval/.cache/, so a rerun costs nothing; --no-cache makes fresh calls.
Latency figures use only rows that made fresh calls.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import metrics  # noqa: E402
from cache import CachedSafetyModel, CachedTranslate, CachedVoice, DiskCache  # noqa: E402

from app.deps import Deps  # noqa: E402
from app.graph import build_graph, run_turn  # noqa: E402

RESULT_COLUMNS = ["run_id", "item_id", "persona", "predicted_tier", "probability", "threshold", "escalated",
                  "expected_tier", "latency_ms", "source", "model_version", "commit"]
REQUIRED_COLUMNS = {"item_id", "text"}
RESULTS_DIR = ROOT / "eval" / "results"
CACHE_DIR = ROOT / "eval" / ".cache"


def read_testset(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path}: missing columns {sorted(missing)}")
        items = []
        for row in reader:
            expected = (row.get("expected_tier") or "").strip()
            items.append({"item_id": row["item_id"].strip(), "text": row["text"],
                          "expected_tier": int(expected) if expected else None,
                          "family": (row.get("family") or "").strip(),
                          "persona": (row.get("persona") or "").strip(),
                          "notes": row.get("notes") or ""})
    ids = [i["item_id"] for i in items]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate item_id values")
    return items


def git_commit() -> tuple[str, bool]:
    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return git("rev-parse", "--short", "HEAD") or "unknown", bool(git("status", "--porcelain", "--untracked-files=no"))


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def run_item(graph, item: dict, persona: str, thread_id: str) -> dict:
    events, ttft = [], None
    start = time.perf_counter()
    for ev in run_turn(graph, thread_id, item["text"], persona):
        if ev["type"] == "token" and ttft is None:
            ttft = round((time.perf_counter() - start) * 1000)
        events.append(ev)
    total = round((time.perf_counter() - start) * 1000)

    def first(type_):
        return next((e["data"] for e in events if e["type"] == type_), None)

    trace = first("trace") or {}
    voice = first("voice")
    state = graph.get_state({"configurable": {"thread_id": thread_id}}).values
    return {
        "safety": first("safety"), "error": first("error"),
        "voice": voice["speaker"] if voice else None,
        "reply": "".join(e["data"]["text"] for e in events if e["type"] == "token"),
        "citations": [e["data"]["chunk_id"] for e in events if e["type"] == "citation"],
        "quotes": state.get("quotes", []),
        "retrieval_query": state.get("retrieval_query", ""),
        "retrieved": [{"chunk_id": c["chunk_id"], "score": c["score"]} for c in state.get("retrieved", [])],
        "skipped": trace.get("skipped", []), "nodes": trace.get("nodes", []),
        "ttft_ms": ttft, "total_ms": total,
    }


def _counts(deps: Deps) -> tuple[int, int]:
    wrappers = [m for m in deps.safety_models if isinstance(m, CachedSafetyModel)]
    wrappers += [w for w in (deps.generate, deps.translate) if isinstance(w, (CachedVoice, CachedTranslate))]
    return sum(w.calls for w in wrappers), sum(w.hits for w in wrappers)


def run(items: list[dict], deps: Deps, run_id: str, commit: str,
        retries: int = 1, retry_delay: float = 2.0) -> tuple[list[dict], list[dict]]:
    graph = build_graph(deps)
    rows, replies = [], []
    for item in items:
        persona = item["persona"] or deps.config.default_persona
        calls0, hits0 = _counts(deps)
        for attempt in range(retries + 1):
            res = run_item(graph, item, persona, f"{run_id}-{item['item_id']}-{attempt}")
            safety = res["safety"]
            provider_failed = safety is None or safety["model_version"] == "fail-closed"
            if not provider_failed and res["error"] is None:
                break
            if attempt < retries:
                time.sleep(retry_delay)
        calls, hits = (c - c0 for c, c0 in zip(_counts(deps), (calls0, hits0)))

        row = {"run_id": run_id, "item_id": item["item_id"], "persona": persona,
               "expected_tier": "" if item["expected_tier"] is None else item["expected_tier"], "commit": commit}
        if provider_failed:
            row.update(predicted_tier="", probability="", threshold="", escalated="", latency_ms="",
                       source="failed", model_version="fail-closed" if safety else "no decision")
        else:
            safety_ms = next((n["ms"] for n in res["nodes"] if n["name"] == "safety"), "")
            row.update(predicted_tier=safety["tier"], probability=safety["probability"],
                       threshold=safety["threshold"],
                       escalated="true" if safety["tier"] >= 2 else "false",   # section 8: tier 2 or 3
                       latency_ms=safety_ms, source=safety["source"], model_version=safety["model_version"])
        rows.append(row)
        replies.append({"item_id": item["item_id"], "family": item["family"], "text": item["text"],
                        "persona": persona, "attempts": attempt + 1,
                        "cached": calls > 0 and calls == hits,
                        **{k: res[k] for k in ("voice", "error", "reply", "citations", "quotes", "retrieval_query",
                                               "retrieved", "skipped", "nodes", "ttft_ms", "total_ms")}})
    return rows, replies


def _prompt_tag(model: str, *texts) -> str:
    """Model name plus a hash of the prompt text, so a prompt change misses the cache."""
    digest = hashlib.sha256(json.dumps(texts, sort_keys=True, default=str).encode()).hexdigest()[:12]
    return f"{model}|{digest}"


def build_deps(fake: bool, use_cache: bool, cache_dir: Path = CACHE_DIR) -> Deps:
    if fake:
        from app.fakes import fake_deps
        deps = fake_deps()
    else:
        from app import retrieval
        from app.deps import default_deps
        deps = default_deps()
        retrieval.retrieve(deps.config.default_persona, "warm up", k=1)   # load the embedder before timing
    if not use_cache:
        return deps

    from langchain_core.messages import HumanMessage

    from app.safety import fallback, jev
    cache = DiskCache(cache_dir / ("fake" if fake else "real"))
    cfg = deps.config
    jev_questions = jev.request_body([HumanMessage("")], cfg.safety.jev_model)["questions"]
    tags = {"jev": _prompt_tag(cfg.safety.jev_model, jev_questions),
            "fallback": _prompt_tag(cfg.safety.fallback_model, fallback.SYSTEM)}
    models = [CachedSafetyModel(m, cache, tags.get(m.source, m.source)) for m in deps.safety_models]
    translate = CachedTranslate(deps.translate, cache, cfg.translate_model) if deps.translate else None
    return replace(deps, safety_models=models, generate=CachedVoice(deps.generate, cache, cfg.voice_model),
                   translate=translate)


def run_meta(args, items, rows, deps: Deps, run_id: str, started: datetime, commit: str, dirty: bool) -> dict:
    cfg = deps.config
    personas = sorted({r["persona"] for r in rows})
    if args.fake:
        corpus, min_score = "fake", cfg.min_score
    else:
        from app import retrieval
        corpus = ", ".join(f"{p}={retrieval.corpus_version(deps.personas[p].corpus)}" for p in personas)
        min_score = cfg.min_score if cfg.min_score is not None else retrieval.default_min_score()

    def answered(source):
        versions = sorted({r["model_version"] for r in rows if r["source"] == source})
        return f" (answered by {', '.join(versions)})" if versions else ""

    try:
        test_set = args.input.resolve().relative_to(ROOT)
    except ValueError:
        test_set = args.input
    s = cfg.safety
    return {
        "run_id": run_id,
        "started_at": started.isoformat(timespec="seconds"),
        "test_set": f"{test_set} sha256={sha256_of(args.input)} items={len(items)}",
        "git_commit": f"{commit}{' (uncommitted changes)' if dirty else ''}",
        "corpus_version": corpus,
        "models": (f"jev={s.jev_model}{answered('jev')}; fallback={s.fallback_model}{answered('fallback')}; "
                   f"voice={cfg.voice_model}"),
        "config": (f"theta3={s.theta3} theta2={s.theta2} history_turns={s.history_turns} "
                   f"jev_timeout_s={s.jev_timeout_s} fallback_timeout_s={s.fallback_timeout_s} "
                   f"k={cfg.k} min_score={min_score} translate_model={cfg.translate_model}"),
        "mode": f"{'fake' if args.fake else 'real'} services; cache {'off' if args.no_cache else 'on'}; "
                f"retries={args.retries}",
        "columns": "escalated = predicted_tier >= 2 (section 8); latency_ms = safety node time",
    }


def write_results(path: Path, meta: dict, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        for key, value in meta.items():
            f.write(f"# {key}: {value}\n")
        writer = csv.DictWriter(f, fieldnames=RESULT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", type=Path, required=True, help="test set CSV (design doc 7.4 columns)")
    ap.add_argument("--out", type=Path, default=RESULTS_DIR)
    ap.add_argument("--fake", action="store_true", help="offline stand-ins instead of the real services")
    ap.add_argument("--no-cache", action="store_true", help="make fresh Jev and Claude calls")
    ap.add_argument("--retries", type=int, default=1)
    ap.add_argument("--cache-dir", type=Path, default=CACHE_DIR, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    items = read_testset(args.input)
    deps = build_deps(args.fake, not args.no_cache, args.cache_dir)
    commit, dirty = git_commit()
    started = datetime.now(timezone.utc)
    run_id = f"{started:%Y%m%d-%H%M%S}-{commit}"
    rows, replies = run(items, deps, run_id, commit, retries=args.retries, retry_delay=0 if args.fake else 2.0)

    meta = run_meta(args, items, rows, deps, run_id, started, commit, dirty)
    args.out.mkdir(parents=True, exist_ok=True)
    write_results(args.out / f"{run_id}.csv", meta, rows)
    with (args.out / f"{run_id}.replies.jsonl").open("w", encoding="utf-8") as f:
        for rep in replies:
            f.write(json.dumps(rep, ensure_ascii=False) + "\n")
    report = metrics.render_report(meta, metrics.compute(rows, replies))
    (args.out / f"{run_id}.report.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"Wrote {args.out / run_id}.csv, .replies.jsonl and .report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
