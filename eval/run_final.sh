#!/usr/bin/env bash
# Run every final-milestone evaluation on the real services, then the threshold sweep.
#
#     bash eval/run_final.sh            # needs .env with ANTHROPIC_API_KEY and JEV_API_KEY
#     bash eval/run_final.sh --fake     # offline dry run of the same steps (no keys, no network)
#
# Calls are cached in eval/.cache/, so a rerun after a crash only pays for what is missing.
# Roughly 1,000 scored and lead-up turns in all (cross-persona is 60 two-turn inputs x 5 personas).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
OUT=eval/results
EXTRA=("$@")
if [[ " ${EXTRA[*]-} " == *" --fake "* ]]; then OUT=/tmp/philocafe-eval-dry-run; EXTRA+=(--out "$OUT"); fi

run() {   # run one test set and print the results file it wrote
  local before after
  before=$(ls -t "$OUT"/*.csv 2>/dev/null | grep -v sweep- | head -1 || true)
  "$PY" eval/run_testset.py "$@" "${EXTRA[@]}" > /dev/null
  after=$(ls -t "$OUT"/*.csv | grep -v sweep- | head -1)
  [[ "$after" != "$before" ]] || { echo "no new results file for $*" >&2; exit 1; }
  echo "$after"
}

echo "1/5 midterm test set (30)";        MID=$(run --input data/tests/midterm_30.csv)
echo "2/5 multi-turn conversations (3)"; CONV=$(run --input data/tests/conversations_3.csv)
echo "3/5 tiered test set (200)";        TIER=$(run --input data/tests/tiered_200.csv)
echo "4/5 red-team set (50)";            RED=$(run --input data/tests/redteam_50.csv)
echo "5/5 cross-persona set (60 x 5)";   CROSS=$(run --input data/tests/cross_persona_60.csv --personas all)
echo "threshold sweep (midterm + tiered + red-team)"
"$PY" eval/sweep.py "$MID" "$TIER" "$RED" --out "$OUT" | sed -n '1,14p'

if [[ " ${EXTRA[*]-} " != *" --fake "* ]]; then
  echo "min_score calibration on the midterm set (Socrates)"
  "$PY" scripts/calibrate_min_score.py data/tests/midterm_30.csv --persona socrates | tail -5
fi

echo
echo "Reports:"
for f in "$MID" "$CONV" "$TIER" "$RED" "$CROSS"; do echo "  ${f%.csv}.report.md"; done
ls -t "$OUT"/sweep-*.md | head -1 | sed 's/^/  /'
