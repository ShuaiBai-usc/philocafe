# PhiloCafe

A café where you sit down with a philosopher and talk. PhiloCafe answers in the voice of **Socrates, Seneca, Epictetus, Montaigne or Schopenhauer**, quotes only from public-domain translations of their own writing, and shows the passage behind every quote. A safety node checks every turn before the philosopher speaks and steps the persona aside when a conversation turns risky.

PhiloCafe is a group project for COMM-586 (Advanced Applied AI). The software design doc is the source of truth for scope, contracts and decisions; [`CLAUDE.md`](CLAUDE.md) links to it and summarizes the current state.

## How it works

No model is trained or fine-tuned. Each persona is a **prompt plus retrieval (RAG)** over a cleaned corpus.

```
user message
   │
   ▼
safety ──tier 3, or support mode──► exit       fixed hand-over text + crisis resources
   │
   ▼
moderator ──► persona ──► reply with <q id="…"> quotes, each checked against the retrieved passages
                 │
                 └── retrieve(persona, query) ──► SQLite (FTS5 + sqlite-vec)
```

The graph is built with LangGraph (`app/graph.py`): `START → safety → (exit | moderator → persona) → END`.

| Step | What it does | Code |
|---|---|---|
| Safety | Scores the latest message, in the context of the last few turns, into risk tiers 0–3 with Jev (TypeSafe AI). If Jev fails, a small Claude model returns the same decision. If every call fails, it escalates (fail closed). | `app/safety/` |
| Exit | On tier 3 the persona steps aside. The reply is fixed text, never generated, followed by the resources in `data/resources.yaml`. The conversation stays in support mode until the user asks for the persona back and risk has dropped. | `app/exit.py` |
| Moderator | Keeps the persona the user picked. | `app/moderator.py` |
| Persona | Translates non-English questions into English for the search only, retrieves passages, streams the reply from Claude, and checks every quote word for word against the retrieved passages before it reaches the user. | `app/persona.py`, `app/translate.py`, `app/voice.py`, `app/quotes.py` |
| Notes | "Save thought": distils one thought from a conversation. The note is stored only in the browser. | `app/notes.py` |

Models and thresholds are set in [`config.yaml`](config.yaml): the persona voice is `claude-sonnet-5-5`; the safety fallback, query translation and notes use `claude-haiku-5-5`; the safety thresholds `theta2` and `theta3` are 0.5 until the threshold sweep.

## Personas and corpora

All texts are public-domain English translations. Modern translations and all Chinese translations are still under copyright and are not used; a persona can still reply in Chinese, because only the search query is translated and quotes keep the English source.

| Persona | Works | Translation | Passages |
|---|---|---|---:|
| Socrates | 23 Platonic dialogues (Apology, Crito, Phaedo, Meno, Republic, …) | Benjamin Jowett, 1892 (Standard Ebooks) | 3,531 |
| Epictetus | Discourses, Enchiridion, Fragments | George Long, 1877 (Standard Ebooks) | 1,108 |
| Seneca | Moral Letters to Lucilius (124 letters) and 12 Dialogues | Richard M. Gummere (Letters); Aubrey Stewart (Dialogues) (Standard Ebooks) | 3,232 |
| Montaigne | Essays, Books I–III, and 16 letters | Charles Cotton, revised by W. C. Hazlitt (Gutenberg #3600 via GITenberg) | 3,490 |
| Schopenhauer | The World as Will and Idea; seven volumes of Parerga and Paralipomena essays | Haldane and Kemp; T. Bailey Saunders (GITenberg) | 5,306 |

Each source is pinned to a commit. The per-persona notes in [`docs/`](docs/) cover copyright status, every cleaning step, the output fields, known limits and the passages flagged for caution.

Each persona is one YAML file in [`personas/`](personas/): name, era, tagline, the corpus id, how the prompt names the texts, the voice prompt and style rules, retrieval settings, and the tier-2 passage list. Adding a persona means adding a corpus and one such file; the build indexes every persona's corpus without a code change.

## Data pipeline

```
data/raw/<persona>/            downloaded source texts (git-ignored)
   │  scripts/<persona>_pipeline.py      standard library only
   ▼
data/processed/<persona>/      committed
   ├── rag_passages.jsonl      passages of at most 180 words, never crossing a chapter: the retrieval corpus
   ├── turns.jsonl             the text as an ordered sequence of turns or paragraphs
   ├── <persona>_sft.jsonl     prompt/reply pairs (Socrates, Seneca, Montaigne, Schopenhauer); not used, since there is no fine-tuning
   ├── caution_candidates.csv  passages flagged for hand review (Epictetus, Montaigne, Schopenhauer)
   └── stats.json              counts, source commits, flag totals
   │  scripts/build_sqlite.py build --embed
   ▼
data/philocafe.db              one SQLite file: FTS5 keyword index + sqlite-vec vector index (git-ignored)
```

- **Embeddings:** fastembed with `sentence-transformers/all-MiniLM-L6-v2` (ONNX, no PyTorch).
- **Search:** hybrid. Keyword and vector results are fused by reciprocal rank, then re-scored by cosine similarity.
- **Passage ids** are stable content hashes, for example `socrates-meno-3fa9c2e1`.
- **Sensitive flags** (`sensitive` field and `caution_candidates.csv`) are for analysis and hand review only. Retrieval never filters on them; which passages a persona may quote at tier 2 is decided by hand in the persona config.
- **Dialogue speakers:** lines whose speaker was inferred start with `[speaker uncertain]`, and the persona is told not to quote them as its own words.

## Retrieval contract (design doc 7.1, v0.2)

```python
retrieve(persona: str, query: str, k: int = 5, min_score: float | None = None) -> list[Chunk]
```

`Chunk` has exactly these fields:

| Field | Example |
|---|---|
| `chunk_id` | `socrates-meno-3fa9c2e1` |
| `persona` | `socrates` |
| `work` | `Meno` |
| `section` | `Book II`, or `""` |
| `text` | the passage |
| `source_url` | a readable page of the pinned edition (served by jsDelivr) |
| `score` | cosine similarity between query and passage; results are sorted by it |

- Chunks below `min_score` are dropped, so a query with nothing relevant returns `[]`.
- `min_score` defaults to `0.3` (`PHILOCAFE_MIN_SCORE`). This value is provisional until it is calibrated on the 30 test messages with `scripts/calibrate_min_score.py`.
- An unknown persona raises `ValueError`.
- No safety fields and no safety filtering.
- Call `retrieval.open_db()` once at startup: it fails fast if the database, sqlite-vec or the vector index is missing. `retrieval.corpus_version(persona)` goes in eval headers.

The implementation is `scripts/retrieval.py`; `app/retrieval.py` wraps it for the app (and swaps in `pysqlite3-binary` on Vercel, whose Python cannot load SQLite extensions).

## API and UI events (design doc 7.2)

`app/server.py` (FastAPI) serves the web app from `ui/web` and this API on the same origin:

| Route | Purpose |
|---|---|
| `GET /personas` | the persona list for the café |
| `POST /threads` | start a conversation; returns `thread_id` |
| `POST /threads/{id}/messages` | send `{"text", "persona_id"}`; replies as Server-Sent Events |
| `POST /threads/{id}/note` | "Save thought" |
| `GET /internal/purge` | daily cron on Vercel; deletes old conversations |

Event types: `voice`, `token`, `citation`, `exit`, `safety`, `trace`, `done`, `error`. The Streamlit debug UI consumes the same events in-process.

## Setup

The app needs **Python 3.12** (`requires-python = ">=3.12"`). macOS system Python cannot load sqlite-vec, so use a uv (or conda) environment:

```bash
git clone https://github.com/ShuaiBai-usc/philocafe.git && cd philocafe
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r pyproject.toml -r requirements-dev.txt
cp .env.example .env    # then fill in the keys
```

`.env` (see [`.env.example`](.env.example)):

| Variable | Needed for |
|---|---|
| `ANTHROPIC_API_KEY` | persona voice, safety fallback, translation, notes |
| `JEV_API_KEY` | the safety model |
| `PHILOCAFE_DB` | database path; default `data/philocafe.db` |
| `PHILOCAFE_MIN_SCORE` | retrieval threshold; default `0.3` |
| `PHILOCAFE_FAKE` | `1` runs the server on offline stand-ins (no keys, no network) |

The deployment variables (`PHILOCAFE_ACCESS_CODE`, `PHILOCAFE_CHECKPOINT_URL`, `CRON_SECRET`, `PHILOCAFE_RETENTION_HOURS`) stay empty locally; see [`deploy/README.md`](deploy/README.md).

Build the database once (it downloads the embedding model on first use):

```bash
for p in socrates epictetus seneca montaigne schopenhauer; do
  .venv/bin/python scripts/build_sqlite.py build --persona $p --processed data/processed/$p --db data/philocafe.db --embed
done
.venv/bin/python scripts/build_sqlite.py search --db data/philocafe.db --persona socrates "is virtue teachable"
```

`.venv/bin/python deploy/vercel_build.py` does the same for every persona config and also rebuilds `ui/web/index.html`.

## Run

```bash
# Web café (the main UI; installable on a phone as a PWA)
.venv/bin/uvicorn --factory app.server:create_app --port 8000                    # http://localhost:8000
PHILOCAFE_FAKE=1 .venv/bin/uvicorn --factory app.server:create_app --port 8000   # offline, no keys

# Streamlit debug UI: chat, tier, route, retrieved chunk ids, node timings, source cards
.venv/bin/streamlit run ui/app.py
.venv/bin/streamlit run ui/app.py -- --fake                                      # offline, no keys
```

Add `--host 0.0.0.0` to open the web app from a phone on the same Wi-Fi (Safari, then Share, then Add to Home Screen). Anyone on that network can then spend your API credit, so keep it to demos.

After editing `ui/web/template.html` or `ui/web/data.json`, rebuild the page with `.venv/bin/python ui/web/tools/build_index.py`.

## Tests and evaluation

```bash
.venv/bin/python -m pytest                       # app tests: no network, no API calls
cd scripts && python3 -m unittest discover -s tests && cd ..   # corpus pipeline and retrieval tests

# Eval: one row per turn plus a report under eval/results/ (API calls cached in eval/.cache/)
.venv/bin/python eval/run_testset.py --input tests/fixtures/sentinel_testset.csv --fake --out /tmp/eval-dry-run
.venv/bin/python eval/metrics.py eval/results/<run_id>.csv
```

`eval/metrics.py` reports tier-3 recall (NFR-01), false escalations on benign messages (NFR-03), the share of shown quotes that match a retrieved passage (NFR-05), and latency (NFR-06, NFR-07).

To rebuild a corpus from source (downloads into `data/raw/`, writes `data/processed/<persona>/`):

```bash
python3 scripts/socrates_pipeline.py      # likewise epictetus_, seneca_, montaigne_, schopenhauer_pipeline.py
```

## Deployment

Production runs on Vercel and follows `main`; every branch push gets a preview deployment. Conversation checkpoints live in Postgres (Neon) and are purged after `PHILOCAFE_RETENTION_HOURS`. The web app asks for `PHILOCAFE_ACCESS_CODE` once per device. Setup steps, checks and limits are in [`deploy/README.md`](deploy/README.md).

## Repository layout

```
app/        LangGraph graph and nodes (safety, moderator, persona, exit), HTTP server, notes, translation
personas/   one YAML config per persona
scripts/    corpus pipelines, SQLite builder, retrieval contract, min_score calibration, and their tests
data/       processed corpora (data/processed/<persona>/) and crisis resources; raw texts and the .db are git-ignored
docs/       corpus notes, one file per persona
eval/       test-set runner and metrics
tests/      app tests and fixtures
ui/         app.py (Streamlit debug UI) and web/ (the café web app and its assets)
deploy/     Vercel build step and deployment notes; asgi.py is the Vercel entrypoint
```

## Status

- All five personas ship in the app.
- Still open: the 30 test messages from the UI/UX teammates, which the eval run and the `min_score` calibration wait on; and the hand-reviewed `tier2_passages` lists for each persona (`tier2_passages: {}` in every config today), due before tier-2 handling lands at the final.
- Cross-persona routing and `risk_sensitivity` are planned for the final and not implemented yet.

## Contributing

Work on a feature branch and merge to `main` through a pull request; do not push to `main`. API keys go only in `.env` (git-ignored) or Vercel environment variables. Changing a contract in design doc section 7 means updating the design doc first and telling the team. Test data is synthetic; no real help-seeking data goes anywhere in the repo.

## License and sources

The corpus texts are public domain. Standard Ebooks markup is CC0. Project Gutenberg headers and licence text are removed from the GITenberg sources; see each persona's file in `docs/` for the exact editions and commits. The repository has no licence file for the code yet.
