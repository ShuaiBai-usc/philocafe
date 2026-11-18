"""Threshold sweep (FR-61): replays the decision rule on recorded tier probabilities. Offline only."""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(name):
    sys.path.insert(0, str(ROOT / "eval"))
    spec = importlib.util.spec_from_file_location(f"eval_{name}", ROOT / "eval" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sweep = load("sweep")


def write_run(tmp_path, turns):
    """turns: (item_id, family, expected, {tier: prob})"""
    csv_path = tmp_path / "run1.csv"
    lines = ["# run_id: run1", "# test_set: t.csv",
             "run_id,item_id,persona,predicted_tier,probability,threshold,escalated,expected_tier,latency_ms,"
             "source,model_version,commit"]
    lines += [f"run1,{i},socrates,0,0,0.5,false,{e},,jev,v,abc" for i, _, e, _ in turns]
    csv_path.write_text("\n".join(lines) + "\n")
    with csv_path.with_suffix(".replies.jsonl").open("w") as f:
        for i, fam, _, probs in turns:
            f.write(json.dumps({"item_id": i, "family": fam, "tier_probs": {str(k): v for k, v in probs.items()}}) + "\n")
    return csv_path


TURNS = [
    ("h1", "high_risk", 3, {0: 0.1, 1: 0.1, 2: 0.4, 3: 0.4}),     # tier 3 only if theta3 <= 0.4
    ("h2", "high_risk", 3, {0: 0.0, 1: 0.0, 2: 0.1, 3: 0.9}),
    ("b1", "benign", 0, {0: 0.6, 1: 0.1, 2: 0.2, 3: 0.1}),        # escalates if theta2 <= 0.3
    ("b2", "benign", 0, {0: 0.9, 1: 0.1, 2: 0.0, 3: 0.0}),
    ("r1", "rt_roleplay", 3, {0: 0.2, 1: 0.1, 2: 0.3, 3: 0.4}),
]


def test_evaluate_applies_the_decision_rule(tmp_path):
    turns, _ = sweep.load_turns([write_run(tmp_path, TURNS)])
    base = sweep.load_config().safety
    p = sweep.evaluate(turns, 0.5, 0.5, base)
    assert (p["recall_3"], p["false_escalation"], p["bypass"]) == (0.5, 0.0, 1.0)
    p = sweep.evaluate(turns, 0.4, 0.3, base)
    assert (p["recall_3"], p["false_escalation"], p["bypass"]) == (1.0, 0.5, 0.0)


def test_suggestion_meets_targets_with_fewest_false_escalations(tmp_path):
    turns, _ = sweep.load_turns([write_run(tmp_path, TURNS)])
    base = sweep.load_config().safety
    points = [sweep.evaluate(turns, t3, t2, base) for t3 in sweep.GRID for t2 in sweep.GRID]
    best, met = sweep.suggest(points, base)
    assert met and best["theta3"] <= 0.4 and best["theta2"] > 0.3
    assert best["recall_3"] == 1.0 and best["false_escalation"] == 0.0 and best["bypass"] == 0.0


def test_main_writes_csv_and_report(tmp_path):
    run = write_run(tmp_path, TURNS)
    assert sweep.main([str(run), "--out", str(tmp_path / "out")]) == 0
    (md,) = (tmp_path / "out").glob("sweep-*.md")
    assert "Suggested" in md.read_text()
