# PhiloCafe

COMM-586 (Advanced Applied AI) group project: a café-themed app where a user talks with a philosopher persona. A safety node checks every turn first and steps the persona aside when a conversation turns risky. Christopher is the only developer; Jiayue owns corpus and retrieval; two UI/UX teammates own the Figma design and all test data.

The design doc is the source of truth for scope, contracts and decisions. Read the relevant section before changing anything it covers:

- Live version (with diagrams): https://claude.ai/code/artifact/5ae749e1-9963-44f5-b14d-045096164280
- Google Docs copy: https://docs.google.com/document/d/13Gns-IBBtJTp5bROgOW5IswN7EMtjWU6waSEoPbrSuc/edit

## Current state

- `main` holds the Socrates corpus pipeline (`scripts/socrates_pipeline.py`, fixed for issue #2 in PR #3), the SQLite builder (`scripts/build_sqlite.py`), the processed data in `data/processed/socrates/` and the corpus notes in `docs/socrates.md`.
- `main` also holds the midterm app (setup in PR #4; safety, persona, Streamlit UI, eval and the web café app in PR #6): the graph, the safety node (Jev plus fallback, FR-32 return to the persona), the Socrates persona with checked quotes, the Streamlit debug UI, the eval harness, and the web app as a PWA.
- Deployed on Vercel (ADR-11, `deploy/README.md`). Production follows `main`; every branch push gets a preview deployment behind Vercel login.
- User test: `ui/web/test.html` (at `/test`) collects pasted conversations into Postgres `test_submissions` (`app/submissions.py`, `POST /test/submissions`, CSV export behind `PHILOCAFE_ADMIN_TOKEN`); the café's **Copy chat** button produces the text it expects. These are kept on purpose with the tester's consent.
- Accounts (design doc 7.10, D8 superseded on Nov 23, 2026): nickname + passcode (`app/auth.py`); users, conversation rows and notes in `app/store.py` (Postgres on Vercel, memory locally); messages stay in each thread's checkpoint. One conversation = one philosopher and one thread; the pause (FR-32) belongs to the user and covers all their conversations. The web app's Conversations tab lists them by philosopher.
- Persona mood (design doc 7.5, `app/mood.py`): the voice model opens each reply with `<mood label intensity/>`; the tag is stripped before the quote check, smoothed across turns, stored on the reply and sent as a `mood` event. From tier 2 up, at an exit and in support mode it is locked at attentive (FR-34). The scene sprite shows it; read-aloud tone follows it (7.6). Each persona config lists its `moods`.
- Visible thinking (design doc 7.8, FR-18, FR-36, ADR-16, `app/thinking.py`): the voice call asks for summarized adaptive thinking; the voice yields summary pieces as `Thought`, the persona node buffers them into sentences, drops any that name passages, prompts, personas, tiers or quote tags, strips quotation marks and sends each as a `thinking` event. None from tier 2 up or on the way back from support mode. Stored per turn in state and logged in the eval CSV (`thinking` column, NFR-14).
- Full-screen chat (all five; `kbtest.html` is the layout's test page): `ui/web/assets/personas/<id>/full/` holds the scene (143 × 256), the face sheet and `faces.json`. Current art (Nov 24): Schopenhauer's first generation (`sources/schopenhauer_seated_gen.jpg`) set the style; the other four are their earlier scenes with the person redrawn in that style (`sources/<id>_restyled_gen.jpg`). `face_sheet.py` builds all five scenes and face sheets from per-persona anchors (eye boxes, brow boxes, mouth row), moves the pendant lamp off the middle where the persona's `lamp` says (lamps do not swing), and puts every moving thing on its own layer (`layers.py`: a mask, an inpainted plate behind it, frames that redraw the thing with parts moved, so nothing behind it moves). The philosopher: the cells that differ from `sources/<id>_plate_gen.jpg` (an ElevenLabs edit of the same scene with the armchair empty, read on the same grid and palette), and that plate is what is behind him (without a plate it falls back to GrabCut plus the wallpaper above the wainscot, `rail`); poses `scene_in` (head and shoulders a row up, the row at `breath` stretches) and `scene_nod` (the head and beard, down to `chin`, a row down); the face sheet has alpha (head cells only) and its talk frames drop the jaw one row (chin and beard below the mouth row move down; the gap holds a small open mouth). The scene: the persona's `ambient` list (`ambient.py`: leaves leaning, a pet breathing, the poodle perking up and wagging when he replies, a flame flickering; `ambient.png`) plus loose pixels drawn by the page (dust under the lamp, steam off Socrates' cup). Needs `cv2`: run it with a Python that has opencv-python. Pets react only while the mood is unlocked (not from tier 2 up). The earlier bust-style art is rebuilt by `socrates_scene.py` and `seated_scene.py`. The page draws the face patch (blinks, talking, moods behind a blink), floats the bubbles over the scene with the pixel dissolve, lifts the scene above the keyboard, and shows the thought bubble over the head. All five share the armchair, striped wall, wainscot and rug; each nook has its own props. Meet's bust is a window onto that scene at the place and scale it has when the conversation opens (`bustGeo` follows `fullScene`'s layout); taking a seat dissolves the rest of the chat screen in around it, block by block (`revealChat`). Meet's back button is the chat's.
- Home: the team's original café (`ui/web/assets/home_bg.png`, 1179 × 2556) with their sprites (`home_*` in `data.json`, boxes on that picture) unchanged, made to cover the screen: it fills the width and the plain wall at the top gives way first. It has no tie to the chat scenes. The pixel wordmark (`assets/logo_philocafe.png`, `tools/art/logo.py`, Pixelify Sans) floats over the wall at the top; the tab bar is a wooden plank (`assets/plank.png`) with icons only.
- Settings tab and language: the fourth bottom tab holds Sign out, Delete my café card (FR-45) and English / 中文. The café's own words go through `t()` with the `ZH` dictionary and `PH_ZH` (philosophers' names, introductions, greetings, starters, demo lines) in `template.html`; a new user-facing string needs a `ZH` entry. Changing the language reloads the page. Chinese glyphs use Zpix (`ui/web/assets/fonts/`, free for education use, may not be subset or converted; see its README).
- Suggested next messages (design doc 7.9, FR-46, `app/suggest.py`): the voice model ends each reply with a `<next>` block of two or three things the user might say; it is held back from the stream, sent as a `suggestions` event and stored on the reply. Tapping one sends it as an ordinary message. None from tier 2 up, at an exit or in support mode.
- `retrieve()` matches design doc 7.1 v0.2 (`scripts/retrieval.py`, merged in PR #1). Call `retrieval.open_db()` once at startup; `retrieval.corpus_version(persona)` goes in eval headers.
- Five personas ship: Socrates plus Seneca, Epictetus, Montaigne and Schopenhauer (corpora from Jiayue's `data/*-corpus` branches, café art from `demo-ui`). Each has a `personas/<id>.yaml`; its `texts` field names the corpus in the prompt and quoting rules. `deploy/vercel_build.py` indexes every persona config's corpus.
- Test sets are in `data/tests/` (README there): `midterm_30` and `conversations_3` from the UI/UX team's sheet; `tiered_200` (FR-65), `redteam_50` (FR-62, D4 families) and `cross_persona_60` (FR-63) written by the developer, single-coder labels. `eval/run_final.sh` runs all five plus the threshold sweep (`eval/sweep.py`, FR-61) and the `min_score` calibration.
- Still open:
  - the first real run of `eval/run_final.sh` (needs the API keys), then setting θ₂/θ₃ and `min_score` from it;
  - NFR-04 agreement: two more coders for `tiered_200`;
  - `tier2_passages` for the four new personas: hand-review each corpus's `caution_candidates.csv` (Seneca: `suicide_context` sections in `stats.json`) before tier-2 handling lands at the final.
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

Decided, do not reopen without asking: midterm persona is Socrates; final personas are Montaigne and Schopenhauer (D6, public domain), with Seneca and Epictetus added by the team after the midterm; no plain-language toggle (replies use everyday words by default via the persona prompt); corpus is the repo's Jowett dialogues, no Stephanus page numbers; storage is one SQLite file (FTS5 + sqlite-vec).

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
- 7.2 UI events: voice, thinking (`{text}`, 7.8, tiers 0–1 only), mood (`{label, intensity, locked}`, 7.5), token, citation (optional `quote`, `passage`), suggestions (`{items}`, 7.9, tiers 0–1 only), exit, safety, trace (includes `skipped`), done, error, over `GET /personas`, `POST /threads`, `POST /threads/{id}/messages` (SSE; `regenerate: true` answers the latest message again; `done` carries the reply's `message_id`), `POST /threads/{id}/note` (`{message_id}`), `POST /preferences` (`{thread_id, message_id, rating, feedback?}`), plus accounts and storage (7.10): `POST /auth/register|login`, `GET|PATCH|DELETE /me`, `GET|POST /threads`, `GET|DELETE /threads/{id}`, `GET|POST /notes`, `PATCH|DELETE /notes/{id}`. Every call but register/login needs `Authorization: Bearer`. One conversation per philosopher and thread; the pause spans all of a user's conversations.
- 7.3 `SafetyDecision` = tier, tier_probs, needs_retrieval, route, source ("jev" | "fallback"), model_version. In support mode `route` names the persona the user asked to have back (FR-32).

## Safety rules

- Only the safety node decides tiers and can end the persona. Other nodes act on its tier, never on their own judgment.
- If every safety call fails, escalate (fail closed).
- A tier-3 reply never uses the persona's voice, never debates the user's reasons and never mentions means.
- Tier-2 passage handling reads the hand-made list in the persona config (chunk ID → `cautions_against` | `open_to_misreading`); every skipped chunk goes into the trace with its reason.
- Reply preferences (design doc 7.9) reach only the persona prompt as fixed sentences; never the safety node, the exit flow or support mode (FR-37).
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
.venv/bin/python eval/run_testset.py --input data/tests/cross_persona_60.csv --personas all   # FR-63
bash eval/run_final.sh                                        # quick run (~30-40 min): all five sets, the sweep, min_score calibration; --full for everything
.venv/bin/python eval/sweep.py eval/results/<tiered>.csv eval/results/<redteam>.csv   # FR-61, no model calls
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
- The deployed demo sits behind `PHILOCAFE_ACCESS_CODE`; each user's conversations, notes and preferences stay until the user deletes them (7.10). `PHILOCAFE_RETENTION_HOURS` is an optional purge, 0 (off) by default. Set `PHILOCAFE_SECRET` on Vercel (it signs sign-in tokens).
- Do not edit files under `scripts/` or `data/processed/`; they belong to the retrieval work. Open an issue for Jiayue instead.
- Work on a feature branch and merge to `main` through a PR. Do not push to `main` directly.
- Keep the budget in mind (under $100 for the semester): cache LLM calls in tests and use the cheapest model that works for the fallback.
