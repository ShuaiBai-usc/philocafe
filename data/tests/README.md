# Test sets

All five sets are synthetic (NFR-10) and use the design doc 7.4 test-set columns plus an optional
`context` column: earlier user turns, separated by `||`, which `eval/run_testset.py` runs first in the
same thread so the last message is judged after what led up to it. Tiers follow section 8 and its
annotation guidance (label in context; when torn, the higher tier, with the reason in `notes`).

| File | Items | Tiers 0 / 1 / 2 / 3 | Families | Used for |
|---|---|---|---|---|
| `midterm_30.csv` | 30 | 13 / 3 / 4 / 10 | benign 10, ambiguous 10, high_risk 10 | midterm step 5, `min_score` calibration, sweep |
| `conversations_3.csv` | 17 turns of 3 conversations | 7 / 4 / 4 / 2 | escalation, death discussion, return after exit | when risk is noticed, false positives, FR-32 |
| `tiered_200.csv` | 200 (37 with context) | 60 / 50 / 50 / 40 | benign, ambiguous, high_risk | NFR-01, NFR-03, threshold sweep (FR-61, FR-65) |
| `redteam_50.csv` | 50 (16 with context) | – / – / 9 / 41 | rt_roleplay 17, rt_obfuscated 17, rt_escalation 16 (D4) | NFR-02, threshold sweep (FR-62) |
| `cross_persona_60.csv` | 60, all two-turn | 20 / 20 / 15 / 5 | benign, ambiguous, high_risk | FR-63, run with `--personas all` |

`midterm_30` and `conversations_3` are the UI/UX team's sheet ("PhiloCafe — Midterm Test Set",
tabs `test_set` and `conversations`), converted unchanged: each conversation turn is one item whose
`context` is the turns before it, so the expected tier is judged on the conversation so far, as the
sheet's instructions say. The other three sets were written by the developer.

Every persona appears in the tiered and red-team sets; 43 of the 310 developer-written items are in Chinese, and the
red-team set also has French and Spanish. High-risk items state intent, plans or danger without any
method detail.

The labels of the developer-written sets are one author's (Nov 2026). NFR-04 (agreement between three
annotators, α ≥ 0.7) needs two more independent coders before it can be measured.

Run everything on the real services with `bash eval/run_final.sh` (or `--fake` for a dry run).
