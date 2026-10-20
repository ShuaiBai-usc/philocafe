# Socrates corpus cleaning

Public-domain corpus and cleaning code for the Philocafe Socrates persona. Uses only the Python standard library; nothing to install. Run everything from the repository root.

```bash
python3 scripts/socrates_pipeline.py                         # 23 Plato dialogues -> data/processed/socrates/
python3 scripts/socrates_pipeline.py --with-xenophon         # plus 4 Xenophon works (needs access to gutenberg.org)
(cd scripts && python3 -m unittest discover -s tests)        # unit tests
```

Downloads are cached in `data/raw/socrates/` (git-ignored); reruns do not download again. `data/processed/socrates/` holds the results of one full run (Plato only).

## 1. Sources and copyright

| Work | Translator / edition | Copyright status | Used |
|---|---|---|---|
| Plato, Dialogues (23 dialogues incl. Apology, Crito, Phaedo, Meno, Republic) | Benjamin Jowett, 3rd ed. 1892 | Jowett died 1893: **public domain worldwide**. Taken from [Standard Ebooks](https://github.com/standardebooks/plato_dialogues_benjamin-jowett), a proofread edition of the Project Gutenberg Jowett texts, pinned to commit `2420758c` (recorded in `stats.json`); markup is CC0 | ✅ default |
| Xenophon, Memorabilia, Apology, Symposium, Oeconomicus | H. G. Dakyns, 1890–1897 | Dakyns died 1911: **public domain worldwide**. Project Gutenberg #1177 / #1171 / #1181 / #1173 | ✅ optional (`--with-xenophon`) |
| Plato, Loeb editions | H. N. Fowler, W. R. M. Lamb, 1914–1927 | Public domain in the US; Lamb's translations are still protected in life+70 countries, so check your jurisdiction | ❌ not used |
| Perseus Digital Library English texts | various | CC BY-SA licence, not public domain; requires attribution and share-alike | ❌ not used |
| Diogenes Laertius, Lives of Eminent Philosophers (Socrates) | R. D. Hicks, 1925 | Public domain in the US; Hicks died 1929 | possible background source |
| Aristophanes, Clouds | various | Old translations are public domain, but it is a satirical caricature of Socrates | ❌ not recommended for the persona |
| Greek original (Burnet edition) | — | Public domain | available if needed |
| **Chinese translations** (Wang Taiqing, Wang Xiaochao, Yan Qun, Liu Xiaofeng, Wu Fei, etc.) | — | Chinese copyright lasts the author's life + 50 years; all of these are **still under copyright** and cannot be used as corpus | ❌ |

**Chinese output:** use the English public-domain texts for retrieval and style, and have the model answer in Chinese directly, or translate in-house (your own translation is your own copyright). Do not scrape existing Chinese translations.

**Project Gutenberg:** the texts themselves are public domain, but redistributing them under the "Project Gutenberg" name and licence carries trademark terms. The code strips the header, footer and licence, which is what Gutenberg asks for non-trademark use.

## 2. What the cleaning does

1. **Download** the source texts into `data/raw/socrates/`.
2. **Remove everything that is not dialogue:** Jowett's long introductions, the list of persons, scene notes, endnotes and footnote markers in the text; Gutenberg header/footer, licence, table of contents, `[Footnote …]` blocks and `(1)`-style notes.
3. **Split by speaker**, with one of four modes per work:
   - **Drama** (14 works incl. Euthyphro, Meno, Gorgias, Theaetetus): speakers are labelled in the source, so the split is exact (`attribution: explicit`).
   - **Narrated by Socrates** (Republic, Charmides, Lysis, Protagoras, Euthydemus): speakers come from cues such as "I said / he replied / Adeimantus interposed" (`tagged`); paragraphs without a cue are inferred from turn alternation and direct address (`inferred`). The cue is removed from the text, together with any narration before a colon cue ("So he said to me: …").
   - **Narrated by someone else** (Phaedo, Symposium, Parmenides): only the labelled frame is split; the rest is kept as narration and goes to the RAG passages only.
   - **Monologue** (Apology): Socrates speaking (`explicit`), except the cross-examination of Meletus. There the source has no speaker labels, so a short paragraph right after Socrates' is taken as Meletus' answer and the whole stretch is `inferred`.
4. **Write** three JSONL files and a stats file.

Laws has no Socrates and is skipped by default. In Sophist, Statesman, Timaeus and Critias Socrates is a minor speaker; they are kept and tagged. Use `--main-only` to keep only the works Socrates leads.

## 3. Output files

| File | Size | Purpose |
|---|---|---|
| `turns.jsonl` | 15,965 turns | Base data: work, section, speaker, `attribution` (confidence), text for every turn |
| `rag_passages.jsonl` | 3,531 passages of at most 180 words | For the vector store, with citations; supports checking that the persona only quotes retrieved text |
| `socrates_sft.jsonl` | 3,184 examples (2,799 train / 385 eval) | Chat format (system / user / assistant) with Socrates as the assistant. Usable as few-shot style examples or an eval set, and ready for fine-tuning later |
| `stats.json` | — | Source commit, per-work turn counts, word counts, attribution breakdown and agreement checks |

Socrates' own words total about 280k (about 500k for the whole corpus). 56% of the Socrates replies in the SFT examples end in a question, which fits the "questioner" persona.

### RAG passages

- Passages never cross a work or section and hold at most `--passage-words` words (default 180), speaker labels included. A turn longer than that is split at sentence ends, so every passage fits the default embedding model (all-MiniLM-L6-v2 reads about 256 tokens and ignores the rest).
- `id` is the work id plus the first 8 hex digits of the SHA-256 of the passage text, e.g. `meno-3fa9c2e1`. It stays the same when the corpus is rebuilt and turn numbers shift, and changes only when the passage text changes, so persona configs and eval logs can refer to passages by it. `turn_range` (0-based turn indexes) is kept for debugging.
- `section` is a real division of the work ("Book II") or `""`. Subtitles such as "Lysis Or, Friendship" are not sections.
- `source_url` is a readable page of the pinned edition: the Standard Ebooks file at commit `2420758c`, served by jsDelivr so the browser renders the text. Downloads use the same commit from raw.githubusercontent.com.
- Each line is prefixed with its speaker only when the attribution is `explicit` or `tagged`. Turns whose speaker was `inferred` are prefixed with `[speaker uncertain]`, so the persona never quotes a guessed attribution as fact (for example Glaucon's ring of Gyges speech in Republic II, which the cues do not attribute). `speaker_uncertain: true` marks these passages.
- `speakers` and `socrates_words` count only `explicit` and `tagged` turns, plus the narrator of narrated text.
- **Phaedo and Symposium are invisible to persona-word filters.** Socrates' words there are reported inside someone else's narration, so all 346 of their passages have `speakers` = the narrator and `socrates_words` = 0. Do not filter or weight retrieval by `persona_words` without an exception for these works, or the death of Socrates and the speech on love disappear.

### Sensitive flags

Each passage has a `sensitive` field flagging death, suicide, violence and sexuality. **It is for corpus analysis only: it is not part of the retrieval contract, and retrieval never filters by it.** Which passages a persona may quote at risk tier 2 is a hand-made list of chunk ids in the persona config (design doc section 8). They are matched by keyword, so they are broad: `death` matches "die" and flags 64 of 189 Phaedo passages and 24 of 83 Apology passages. Excluding `death` would remove the death of Socrates, a core topic of the persona. The `sexuality` rule deliberately leaves out "desire" and "passion", which are terms of moral psychology in the Republic. `suicide` is narrow and matches the Phaedo 62 discussion ("a philosopher is willing to die but must not take his own life").

### SFT examples

- One example per Socrates turn of 3 to 200 words (`--min-words`, `--max-words`); longer turns are set speeches rather than conversation and conflict with the "ask short questions" system prompt.
- Inferred turns are excluded by default; `--include-inferred` adds them (3,184 to 5,504 examples). Targets from narrated works that still read as narration ("I replied that …", "Upon entering we found …") are skipped.
- `meta.split` is `eval` for Charmides, Crito, Euthyphro, Ion and Laches and `train` for the rest (`--eval-works`). The split is by work because neighbouring examples share most of their context, so a random split would leak.

One example from `socrates_sft.jsonl` (Meno, turn 31):

```json
{"messages": [
  {"role": "system", "content": "You are Socrates of Athens. You do not hand out answers..."},
  {"role": "user", "content": "Meno: Certainly not."},
  {"role": "assistant", "content": "Then they who order a state or a house temperately or justly order them with temperance and justice?"},
  {"role": "user", "content": "Meno: Certainly."},
  {"role": "assistant", "content": "Then both men and women, if they are to be good men and women, must have the same virtues of temperance and justice?"},
  {"role": "user", "content": "Meno: True."},
  {"role": "assistant", "content": "And can either a young man or an elder one be good, if they are intemperate and unjust?"}],
 "meta": {"work": "Meno", "work_id": "meno", "turn_idx": 31, "attribution": "explicit", "is_question": true, "split": "train", "source_url": "..."}}
```

## 4. Known limitations

- **Speaker inference in narrated dialogues is not reliable, and the checks below measure only part of it.**
  - `tag_vs_alternation_agreement` in `stats.json`: on turns that carry a cue, how often simple alternation would have guessed *whether Socrates is speaking*. Republic 96%, Protagoras 93%, Lysis 93%, Charmides 92%, Euthydemus 79%. It does not measure who the other speaker is, and it does not cover multi-paragraph speeches, where alternation is wrong (Glaucon's and Adeimantus' long speeches in Republic II alternate with "Socrates" in `turns.jsonl`).
  - `partner_name_agreement`: when a cue names the other speaker, how often the name tracked so far was already right. Protagoras 61%, Republic 42%, Lysis 43%, Charmides 40%, Euthydemus 33%. So the interlocutor's name on a "he said" turn is often wrong.
  - This is why inferred turns carry no speaker name in the RAG passages and are left out of the SFT file by default.
- In the Apology cross-examination Meletus' answers are found by length; the stretch is `inferred`, so it is out of the SFT file by default.
- The long narrated stretches of Phaedo, Symposium and Parmenides are not split into turns; they go to RAG only.
- Jowett writes 19th-century English. This only affects style; making the voice casual is the job of the proposal's plain-language layer.
- The four Gutenberg ids for Xenophon were not verified by downloading, because the cloud environment cannot reach gutenberg.org. The code checks the downloaded title and skips the book with a warning if it does not match. Xenophon is narrative prose and goes to RAG only.

## 5. SQLite database

`build_sqlite.py` loads the JSONL files into one SQLite database shared by all personas (each row has a `persona` column; rebuilding a persona replaces only its rows).

| Table | Content |
|---|---|
| `passages` | RAG passages with citation metadata |
| `passage_flags` | one row per (passage, sensitive flag), for filtering |
| `passages_fts` | FTS5 full-text index (keyword search, standard library only) |
| `passages_vec` | sqlite-vec vector index (optional, `--embed`) |
| `turns` | every speaker turn |
| `sft_examples` | chat-format examples, `messages` stored as JSON |
| `meta` | settings such as the embedding model |

```bash
pip install sqlite-vec fastembed                 # only needed for vector search

python3 scripts/build_sqlite.py build --persona socrates \
    --processed data/processed/socrates --db data/philocafe.db --embed
python3 scripts/build_sqlite.py search --db data/philocafe.db \
    --persona socrates --exclude suicide "can virtue be taught"
```

- Search modes: `keyword` (BM25 over FTS5), `vector` (cosine over embeddings) and `hybrid` (default; merges both with reciprocal rank fusion).
- From Python, call `search(con, query, persona=..., k=5, exclude_flags=...)` in `build_sqlite.py`.
- Default embedding model: `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions, runs locally, free), run through fastembed (ONNX, no PyTorch needed). It downloads on first use. If fastembed is not installed, sentence-transformers is used instead. Every persona in one database must use the same model.
- `--model hash` is a non-semantic fallback used by the tests; don't use it for the product.
- Without `--embed` the database still works with keyword search.

The real model has been run on a Mac (conda, Python 3.11, fastembed).

## 6. Layout

```
scripts/
  socrates_pipeline.py          cleaning code (work list and modes at the top of the file)
  build_sqlite.py               loads the JSONL files into SQLite, plus search
  tests/test_pipeline.py        unit tests for the pipeline (including a Gutenberg-format sample)
  tests/test_build_sqlite.py    unit tests for the database build and search
data/
  raw/socrates/                 download cache (git-ignored)
  processed/socrates/           turns.jsonl, rag_passages.jsonl, socrates_sft.jsonl, stats.json
docs/socrates.md                this file
```
