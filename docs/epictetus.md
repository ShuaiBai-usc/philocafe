# Epictetus corpus

Public-domain corpus and cleaning code for the Philocafe Epictetus persona. It follows the Socrates pipeline (`docs/socrates.md`): same output files, same passage schema, same SQLite build. Standard library only.

```bash
python3 scripts/epictetus_pipeline.py                 # downloads the pinned texts once into data/raw/epictetus/
(cd scripts && python3 -m unittest discover -s tests)

python3 scripts/build_sqlite.py build --persona epictetus \
    --processed data/processed/epictetus --db data/philocafe.db --embed
```

`epictetus_pipeline.py` imports the shared helpers (`Turn`, `fetch`, `el_text`, `split_words`, ...) from `socrates_pipeline.py`, so both must sit in `scripts/`.

## 1. Sources and copyright

| Work | Translator / edition | Copyright status | Used |
|---|---|---|---|
| Discourses, Books I–IV (recorded by Arrian) | George Long, 1877 | Long died 1879: **public domain worldwide**. Taken from [Standard Ebooks](https://github.com/standardebooks/epictetus_discourses_george-long), pinned to commit `a50e918f`; markup is CC0 | ✅ |
| Enchiridion and Fragments | George Long, 1877 | Same. [Standard Ebooks Short Works](https://github.com/standardebooks/epictetus_short-works_george-long), pinned to commit `8c154d40` | ✅ |
| Discourses, Enchiridion | Elizabeth Carter, 1758 | Public domain worldwide | ❌ not used (older English than Long; no Standard Ebooks edition) |
| Loeb edition | W. A. Oldfather, 1925–1928 | Public domain in the US; Oldfather died 1945, so also out of copyright in life+70 countries. Plainer English than Long, but no proofread source reachable from here | ❌ possible upgrade |
| Robin Hard, Robin Waterfield, A. A. Long, etc. | modern | under copyright | ❌ |
| **Chinese translations** | — | still under copyright, as for Socrates | ❌ |

Both commits are recorded in `stats.json`. Every `source_url` points to the pinned file on jsDelivr with the chapter anchor, e.g. `.../book-1.xhtml#chapter-1-1`, so a citation opens at the right chapter.

## 2. What the cleaning does

1. **Download** the six XHTML files (four books, Enchiridion, Fragments), cached in `data/raw/epictetus/`.
2. **Keep only Epictetus' text.** Dropped: Long's introduction, Arrian's preface letter, endnotes and footnote markers, the editor's introduction to the Fragments, and Fragments CLXXIX–CLXXXI, which are Latin quotations (Aulus Gellius, Arnobius).
3. **Greek glosses** are removed: "opinion (ὑπόληψις)" becomes "opinion", "aversion (ἔκκλισις, turning from a thing)" becomes "aversion (turning from a thing)". Long's English glosses ("desire (aim at)") and his bracketed supplements ("[By no means.]") are part of the translation and are kept.
4. **Verse and quoted plays** inside a paragraph stay in that paragraph's turn (the quoted Phoenissae scene reads "Polynices: ... Eteocles: ...").
5. **Turns** are paragraphs. There are no dialogues to split by speaker, so the modes differ from Socrates:

| Work | Section format | `speaker` / `attribution` |
|---|---|---|
| Discourses | `Book I, Chapter 11` plus `chapter_title` ("Of Natural Affection") | `Epictetus` / `explicit` for the lectures. Where Arrian frames a chapter ("When a man was consulting him ..., Epictetus replied:"), the frame becomes an `Arrian` / `narration` turn and the rest an `Epictetus` / `tagged` turn. Paragraphs where Arrian reports a whole exchange in quotations (1.11, 1.26, 2.24, 3.22 ...) are `narration` as a whole. |
| Enchiridion | `Chapter 33` | `Epictetus` / `explicit` |
| Fragments | `Fragment 172` | `Epictetus` / `attributed`: collected by Stobaeus and later monks; Long says some "are certainly not from Epictetus" |

Turn indices run per work.

## 3. Output files

Run results are in `data/processed/epictetus/`:

| File | Size | Purpose |
|---|---|---|
| `turns.jsonl` | 661 turns | One record per paragraph, with `chapter_title` |
| `rag_passages.jsonl` | 1,108 passages (Discourses 855, Enchiridion 73, Fragments 180) | For the vector store. Same fields as Socrates, with `epictetus_words` instead of `socrates_words` (`build_sqlite.py` reads `<persona>_words`), plus `chapter_title` and `attribution` |
| `caution_candidates.csv` | 16 rows | Passages flagged `suicide`, with their `chunk_id`, for the persona config's tier-2 caution list |
| `stats.json` | — | Per-work counts, flags, pinned commits |

About 130k words of Epictetus (Discourses 115k, Enchiridion 8k, Fragments 7k).

Passages never cross a chapter, so each has one citation. Long chapters are split at sentence ends into pieces of at most 180 words. Many Fragments and Enchiridion chapters are a single sentence, so 62 passages are under 20 words; they are not merged with neighbours because unrelated maxims would blur the embedding.

Ids follow design doc v0.2: passage `id` = `<work>-<8 hex of SHA-256 of the text>` (e.g. `enchiridion-bffc1667`), `chunk_id` = `epictetus-<id>`, stable unless the text changes.

### No SFT file

Socrates' SFT examples pair an interlocutor's line with Socrates' reply. Epictetus' works are lectures and maxims; the only real exchanges are a handful of Arrian's reports, in quotations, without reliable speaker splits. Making SFT pairs would mean inventing the user turns, so no `epictetus_sft.jsonl` is written (ADR-03 does not use SFT anyway). `build_sqlite.py` skips the missing file.

## 4. Sensitive content

`sensitive` uses the Socrates keys (`suicide`, `death`, `violence`, `sexuality`) and stays out of the retrieval contract, as for Socrates.

**Epictetus defends leaving life when it becomes unbearable**, mostly in euphemisms: "the door is open", "if the smoke is excessive, I go out", "God gives the signal for retreat", "is it not in your power to die?". The `suicide` pattern therefore matches these phrases as well as the literal ones. All 16 flagged passages were read and are true positives (one is 2.15, where Epictetus talks a friend out of starving himself; two are the insult "Will you not hang yourself?"). They are listed in `caution_candidates.csv` for the persona config. Retrieval does not filter them; the persona prompt should not present this teaching as advice to a user in distress.

Other counts: `death` 123 (death is a central Stoic topic, so this flag is a hint only), `sexuality` 34 (includes adultery), `violence` 23.

## 5. Known limitations

- Lecture paragraphs often contain the imagined or real interlocutor's lines inline ("I do, the person replied."). `speaker: Epictetus` means "Epictetus' lecture", not that every sentence is his.
- Arrian's framed exchanges in quotations stay whole as narration, so their Epictetus words do not count in `epictetus_words` (about 2,500 words). Their text is still in the passages.
- Long writes 1870s English with frequent parenthetical glosses ("(hope)", "(aim at)"). The plain-language layer handles style; Oldfather is the alternative if a plainer translation is wanted.
- Epictetus was a slave and often speaks of slaves, chains and beatings as examples. This is not flagged separately.

## 6. Layout

```
scripts/epictetus_pipeline.py               cleaning code (sources and work list at the top)
scripts/tests/test_epictetus_pipeline.py    unit tests
data/processed/epictetus/                   run results (data/raw/ is git-ignored)
```
