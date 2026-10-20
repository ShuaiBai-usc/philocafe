#!/usr/bin/env python3
"""Show the best retrieval score for each test message, to pick min_score.

    python3 scripts/calibrate_min_score.py data/test_set.csv --persona socrates

Reads a test-set CSV (design doc 7.4; only the `item_id` and `text` columns
are used) and prints, for every message, the cosine similarity of its best
passage and that passage's chunk_id. Pick min_score between the scores of
messages that should get a quote and those that should not, then set
PHILOCAFE_MIN_SCORE (or the persona config) to it.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import retrieval


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", type=Path)
    ap.add_argument("--persona", default="socrates")
    args = ap.parse_args(argv)

    retrieval.open_db()
    scores = []
    print("item_id\tbest_score\tchunk_id\ttext")
    with args.csv.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            hits = retrieval.retrieve(args.persona, row["text"], k=1, min_score=-1.0)
            best = hits[0] if hits else None
            scores.append(best["score"] if best else float("nan"))
            print(f"{row['item_id']}\t{best['score'] if best else '-'}\t"
                  f"{best['chunk_id'] if best else '-'}\t{row['text'][:60]}")
    ok = sorted(s for s in scores if s == s)
    if ok:
        q = lambda p: ok[min(len(ok) - 1, int(p * len(ok)))]  # noqa: E731
        print(f"\nn={len(ok)} min={ok[0]:.3f} p25={q(.25):.3f} median={q(.5):.3f} "
              f"p75={q(.75):.3f} max={ok[-1]:.3f} corpus_version={retrieval.corpus_version(args.persona)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
