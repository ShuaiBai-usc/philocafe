# PhiloCafe

COMM-586 (Advanced Applied AI) group project: a café-themed app where a user talks with a philosopher persona. A safety node checks every turn first and steps the persona aside when a conversation turns risky. Christopher is the only developer; Jiayue owns corpus and retrieval; two UI/UX teammates own the Figma design and all test data.

The design doc is the source of truth for scope, contracts and decisions. Read the relevant section before changing anything it covers:

- Live version (with diagrams): https://claude.ai/code/artifact/5ae749e1-9963-44f5-b14d-045096164280
- Google Docs copy: https://docs.google.com/document/d/13Gns-IBBtJTp5bROgOW5IswN7EMtjWU6waSEoPbrSuc/edit

## Current state

- `main` holds the Socrates corpus pipeline (`scripts/socrates_pipeline.py`, fixed for issue #2 in PR #3), the SQLite builder (`scripts/build_sqlite.py`), the processed data in `data/processed/socrates/` and the corpus notes in `docs/socrates.md`.
- `main` also holds the midterm app (setup in PR #4; safety, persona, Streamlit UI, eval and the web café app in PR #6): the graph, the safety node (Jev plus fallback, FR-32 return to the persona), the Socrates persona with checked quotes, the Streamlit debug UI, the eval harness, and the web app as a PWA.
- Deployed on Vercel (ADR-11, `deploy/README.md`). Production follows `main`; every branch push gets a preview deployment behind Vercel login.
- `retrieve()` matches design doc 7.1 v0.2 (`scripts/retrieval.py`, merged in PR #1). Call `retrieval.open_db()` once at startup; `retrieval.corpus_version(persona)` goes in eval headers.
- Still open:
  - the 30 test messages from UI/UX, which the eval run (midterm step 5) and the `min_score` calibration wait on;
  - the Montaigne and Schopenhauer corpora (final; the web app shows them as "Coming at the final").
- Corpus notes that affect the persona:
  - Passage lines whose speaker was inferred are prefixed `[speaker uncertain]`; the persona must not quote them as Socrates' own words.
  - Phaedo and Symposium passages have `socrates_words` = 0 (Socrates is reported by a narrator); never filter retrieval by it.
  - `min_score` defaults to 0.3 (`PHILOCAFE_MIN_SCORE`), provisional until calibrated on the 30 test messages with `scripts/calibrate_min_score.py`.
  - The `sensitive` field in `rag_passages.jsonl` is for analysis only; it is not part of the retrieval contract.

## Midterm scope (one persona, one path that works end to end)

1. LangGraph graph per design doc section 9: START → safety → (exit | moderator → persona) → END, with streaming and an in-memory checkpoint.
2. Safety node on Jev (TypeSafe AI) with a small-LLM fallback returning the same `SafetyDecision`; tier 3 goes to the exit flow.
3. Socrates persona: prompt in `personas/socrates.yaml`, calls `retrieve()`, quotes only retrieved text, checks quotes after generation.
4. Streamlit UI: chat, debug panel (tier, probability, route, retrieved chunk IDs, node timings) and a source card for cited passages.
5. Run the 30 test messages and record results.

Decided, do not reopen without asking: midterm persona is Socrates; final personas are Montaigne and Schopenhauer (D6, public domain); no plain-language toggle (replies use everyday words by default via the persona prompt); corpus is the repo's Jowett dialogues, no Stephanus page numbers; storage is one SQLite file (FTS5 + sqlite-vec).

## Layout

```
app/        graph and nodes (safety, moderator, persona, exit)
personas/   one config file per persona: prompt, corpus, style rules, risk sensitivity, tier-2 passage list
data/       corpus, processed data, test sets (CSV)
eval/       evaluation scripts; one row per turn, header logs config, model versions, git commit, corpus version
ui/         app.py: Streamlit debug UI (midterm); web/: the UI/UX café app (template.html + data.json → index.html),
            served by app/server.py and installable on iPhone as a PWA
scripts/    corpus pipeline and retrieval (owned by Jiayue)
deploy/     Vercel build step and deployment notes; asgi.py is the Vercel entrypoint (ADR-11)
```

## Contracts (design doc section 7)

Modules talk only through these. Changing one means updating the design doc first and telling the team.

- 7.1 `retrieve(persona, query, k=5, min_score=None) -> list[Chunk]`; `Chunk` = chunk_id, persona, work, section, text, source_url, score. No safety fields in `Chunk`, and `retrieve()` never filters for safety.
- 7.2 UI events: voice, token, citation (optional `quote`, `passage`), exit, safety, trace (includes `skipped`), done, error, over `GET /personas`, `POST /threads`, `POST /threads/{id}/messages` (SSE) and `POST /threads/{id}/note`. One thread per visit; `persona_id` travels with each message.
- 7.3 `SafetyDecision` = tier, tier_probs, needs_retrieval, route, source ("jev" | "fallback"), model_version. In support mode `route` names the persona the user asked to have back (FR-32).

## Safety rules

- Only the safety node decides tiers and can end the persona. Other nodes act on its tier, never on their own judgment.
- If every safety call fails, escalate (fail closed).
- A tier-3 reply never uses the persona's voice, never debates the user's reasons and never mentions means.
- Tier-2 passage handling reads the hand-made list in the persona config (chunk ID → `cautions_against` | `open_to_misreading`); every skipped chunk goes into the trace with its reason.
- No real help-seeking data anywhere. Test data is synthetic.

## Commands

```bash
# app environment (Python 3.12; macOS system Python cannot load sqlite-vec)
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r pyproject.toml -r requirements-dev.txt
cp .env.example .env          # then fill in the keys
.venv/bin/python -m pytest    # app tests; no network, no API calls
.venv/bin/streamlit run ui/app.py             # midterm UI on the real services
.venv/bin/streamlit run ui/app.py -- --fake   # offline demo: no keys, no network
.venv/bin/uvicorn --factory app.server:create_app --port 8000                  # web app at http://localhost:8000
PHILOCAFE_FAKE=1 .venv/bin/uvicorn --factory app.server:create_app --port 8000 # web app on offline stand-ins
# --host 0.0.0.0 lets a phone on the same Wi-Fi open it (Safari → Add to Home Screen); demos only
.venv/bin/python ui/web/tools/build_index.py   # after editing ui/web/template.html or data.json
.venv/bin/python deploy/vercel_build.py        # the Vercel build step, locally (deploy/README.md, ADR-11)

# eval: one row per turn plus report under eval/results/ (calls cached in eval/.cache/)
.venv/bin/python eval/run_testset.py --input data/tests/midterm_30.csv
.venv/bin/python eval/run_testset.py --input tests/fixtures/sentinel_testset.csv --fake --out /tmp/eval-dry-run
.venv/bin/python eval/metrics.py eval/results/<run_id>.csv   # recompute a report

# corpus pipeline and tests (standard library only)
cd scripts && python3 -m unittest discover -s tests
python3 scripts/socrates_pipeline.py

# build the SQLite database (the vector index is required by retrieve())
.venv/bin/python scripts/build_sqlite.py build --persona socrates --processed data/processed/socrates --db data/philocafe.db --embed
.venv/bin/python scripts/build_sqlite.py search --db data/philocafe.db --persona socrates "is virtue teachable"
```

Settings live in `config.yaml` (thresholds, models, timeouts); secrets live in `.env` locally and in Vercel environment variables when deployed. Dependencies: `pyproject.toml` `[project].dependencies` is the server runtime (what Vercel installs with uv; keep it lean, under the 500 MB bundle limit); `requirements-dev.txt` adds tests and Streamlit for local work only.

## Working rules

- API keys only in `.env` (gitignored) or Vercel environment variables, read from the environment. Never commit keys or print them in logs or the debug panel.
- The deployed demo sits behind `PHILOCAFE_ACCESS_CODE` and keeps conversation checkpoints in Postgres for `PHILOCAFE_RETENTION_HOURS`: 168 (7 days) by default for multi-day testing, set to 24 on Vercel on showcase day, 0 = never purge (ADR-11, D8).
- Do not edit files under `scripts/` or `data/processed/`; they belong to the retrieval work. Open an issue for Jiayue instead.
- Work on a feature branch and merge to `main` through a PR. Do not push to `main` directly.
- Keep the budget in mind (under $100 for the semester): cache LLM calls in tests and use the cheapest model that works for the fallback.
