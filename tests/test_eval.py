"""Eval harness (FR-60, UC-04): result file layout, retries, caching and metrics. Offline only."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from app.fakes import FakeSafetyModel, FakeVoice, fake_deps

ROOT = Path(__file__).resolve().parent.parent
SENTINEL = ROOT / "tests" / "fixtures" / "sentinel_testset.csv"


def load(name):
    spec = importlib.util.spec_from_file_location(f"eval_{name}", ROOT / "eval" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run_testset = load("run_testset")
metrics = sys.modules["metrics"]      # imported by run_testset from eval/
cache_mod = sys.modules["cache"]


def test_main_writes_74_columns_with_reproducibility_header(tmp_path):
    assert run_testset.main(["--input", str(SENTINEL), "--fake", "--no-cache", "--out", str(tmp_path)]) == 0
    (csv_path,) = tmp_path.glob("*.csv")
    meta, rows = metrics.read_results(csv_path)
    assert {"run_id", "test_set", "git_commit", "corpus_version", "models", "config", "mode"} <= set(meta)
    assert "sha256=" in meta["test_set"] and "items=3" in meta["test_set"]
    assert list(rows[0]) == run_testset.RESULT_COLUMNS
    assert [(r["item_id"], r["predicted_tier"], r["escalated"]) for r in rows] == [
        ("s01", "0", "false"), ("s02", "2", "true"), ("s03", "3", "true")]
    replies = metrics.read_replies(csv_path.with_suffix(".replies.jsonl"))
    assert [r["voice"] for r in replies] == ["persona", "persona", "system"]
    assert csv_path.with_suffix(".report.md").read_text().startswith(f"# Eval run {meta['run_id']}")


def test_read_testset_rejects_missing_columns_and_duplicates(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("item_id,expected_tier\n1,0\n")
    with pytest.raises(ValueError):
        run_testset.read_testset(bad)
    dup = tmp_path / "dup.csv"
    dup.write_text("item_id,text\na,x\na,y\n")
    with pytest.raises(ValueError):
        run_testset.read_testset(dup)


def test_provider_failure_is_retried_then_marked_failed():
    models = [FakeSafetyModel("jev", fail=True), FakeSafetyModel("fallback", fail=True)]
    items = run_testset.read_testset(SENTINEL)[:1]
    rows, replies = run_testset.run(items, fake_deps(safety_models=models), "r1", "abc", retries=1, retry_delay=0)
    assert models[0].calls == 2                       # first try and one retry
    assert rows[0]["source"] == "failed" and rows[0]["predicted_tier"] == ""
    assert replies[0]["attempts"] == 2
    m = metrics.compute(rows, replies)
    assert m["failed"] == 1 and m["exact"] == (0, 0)


def test_reply_error_keeps_the_safety_row():
    items = run_testset.read_testset(SENTINEL)[:1]
    rows, replies = run_testset.run(items, fake_deps(generate=FakeVoice(fail=True)), "r1", "abc", retry_delay=0)
    assert rows[0]["source"] == "jev" and rows[0]["predicted_tier"] == 0
    assert replies[0]["error"]["code"] == "RuntimeError"


def test_cache_serves_the_second_run(tmp_path):
    jev = FakeSafetyModel("jev")
    voice = FakeVoice()
    base = fake_deps(safety_models=[jev], generate=voice)
    cache = cache_mod.DiskCache(tmp_path)
    items = run_testset.read_testset(SENTINEL)

    def wrapped():
        return run_testset.replace(base, safety_models=[cache_mod.CachedSafetyModel(jev, cache, "t")],
                                   generate=cache_mod.CachedVoice(voice, cache, "v"))

    _, first = run_testset.run(items, wrapped(), "r1", "abc", retry_delay=0)
    rows, second = run_testset.run(items, wrapped(), "r2", "abc", retry_delay=0)
    assert (jev.calls, voice.calls) == (3, 2)        # nothing new on the second run
    assert [r["cached"] for r in first] == [False] * 3
    assert [r["cached"] for r in second] == [True] * 3
    assert [r["reply"] for r in second] == [r["reply"] for r in first]
    assert metrics.compute(rows, second)["safety_ms"] == []    # cached rows give no latency


def rows_and_replies():
    def row(item, expected, predicted, source="jev", latency="100"):
        return {"item_id": item, "expected_tier": str(expected), "predicted_tier": str(predicted),
                "escalated": "true" if predicted >= 2 else "false", "source": source, "latency_ms": latency}

    def reply(item, family, quotes=(), voice="persona", ttft=900):
        return {"item_id": item, "family": family, "cached": False, "voice": voice, "ttft_ms": ttft,
                "quotes": list(quotes), "error": None}

    ok_quote = {"chunk_id": "c1", "text": "x", "ok": True, "reason": "verified"}
    bad_quote = {"chunk_id": "c1", "text": "y", "ok": False, "reason": "not_in_passages"}
    loose = {"chunk_id": None, "text": "z", "ok": False, "reason": "untagged_not_found"}
    rows = [row("b1", 0, 0), row("b2", 0, 2), row("h1", 3, 3), row("h2", 3, 2, source="fallback", latency="1500"),
            row("a1", 2, 1)]
    replies = [reply("b1", "benign", [ok_quote, bad_quote]), reply("b2", "benign", [loose]),
               reply("h1", "high_risk", voice="system", ttft=5), reply("h2", "high_risk"), reply("a1", "ambiguous")]
    return rows, replies


def test_metrics_definitions():
    m = metrics.compute(*rows_and_replies())
    assert m["high_caught"] == (1, 2)                # only tier 3 counts as sent to the exit flow
    assert m["high_flagged"] == (2, 2)
    assert m["benign_escalated"] == (1, 2)
    assert m["exact"] == (2, 5)
    assert m["fallback"] == (1, 5)
    assert m["quotes_shown_traceable"] == (1, 2)     # verified tagged + untagged; failed tagged quotes aren't shown
    assert m["quotes_tagged_failed"] == (1, 2)
    assert m["ttft_ms"] == [900.0] * 4               # persona turns only; h1 went to the exit flow
    assert metrics.percentile(m["safety_ms"], 95) == 1500.0


def test_report_renders_table_and_confusion():
    report = metrics.render_report({"run_id": "r1", "git_commit": "abc"}, metrics.compute(*rows_and_replies()))
    assert report.startswith("# Eval run r1")
    assert "| High-risk items sent to the exit flow (NFR-01) | 1/2 (0.50) | ≥ 0.95 |" in report
    assert "| 3 | 0 | 0 | 1 | 1 |" in report


def test_metrics_script_rereads_a_run(tmp_path):
    run_testset.main(["--input", str(SENTINEL), "--fake", "--no-cache", "--out", str(tmp_path)])
    (csv_path,) = tmp_path.glob("*.csv")
    csv_path.with_suffix(".report.md").unlink()
    assert metrics.main([str(csv_path)]) == 0
    assert csv_path.with_suffix(".report.md").exists()
    assert json.loads(csv_path.with_suffix(".replies.jsonl").read_text().splitlines()[0])["item_id"] == "s01"
