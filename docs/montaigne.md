# Montaigne corpus cleaning

Public-domain corpus and cleaning code for the Philocafe Montaigne persona. It follows the Seneca pipeline (`docs/seneca.md`), which in turn follows the Socrates pipeline and the design doc v0.2 retrieval contract, and writes the same files, so `build_sqlite.py` and `retrieval.py` work without changes. Python standard library only.

```bash
# from the philocafe/ repository root (script in scripts/, outputs git-ignored as for Socrates)
python3 scripts/montaigne_pipeline.py                         # -> data/processed/montaigne, cache in data/raw/montaigne
python3 scripts/montaigne_pipeline.py --with-topic-prompts    # also one templated example per essay
python3 -m unittest discover -s scripts/tests -p 'test_montaigne*'

python3 scripts/build_sqlite.py build --persona montaigne \
    --processed data/processed/montaigne --db data/philocafe.db --embed
```

In this shared folder: `python3 montaigne_pipeline.py --out output --raw raw` and `python3 -m unittest discover -s tests`. `output/` holds one full run.

## 1. Sources and copyright

| Work | Translator / edition | Copyright status | Used |
|---|---|---|---|
| Essays, Books I–III (all 107 chapters) and "To the Reader" | Charles Cotton (1685–1686), revised and edited by William Carew Hazlitt (1877) | Cotton died 1687, Hazlitt 1913: **public domain worldwide** | ✅ |
| Letters of Montaigne (16 letters, incl. the letter to his father on the death of La Boétie) | same edition | same | ✅ (`--no-letters` leaves them out) |
| Hazlitt's preface and *Life of Montaigne*; the editors' notes | Hazlitt, Coste, Widger | not Montaigne's text | ❌ |
| Florio's translation (1603) | John Florio | Public domain, but Elizabethan spelling ("vsuall waie") would hurt retrieval and voice | ❌ |
| Modern translations (Frame, Screech, Chinese translations) | — | Under copyright | ❌ |
| Travel Journal | — | not in this edition | ❌ |

Standard Ebooks has no Montaigne edition, and gutenberg.org cannot be reached from the cloud sandbox, so the text comes from the **GITenberg** mirror of Project Gutenberg eBook #3600 (HTML edition by David Widger) on GitHub, pinned to a commit and recorded in `stats.json`:

- `GITenberg/Essays-of-Michel-de-Montaigne---Complete_3600` @ `a538bae9`, file `3600-h/3600-h.htm`

The Project Gutenberg header, licence and trademark text are not part of the output (the text itself is public domain; the PG licence only governs redistribution under the PG name). `source_url` points to the same pinned file served by jsDelivr, with the chapter's anchor (`...3600-h.htm#link2HCH0019`), so the browser jumps to the right essay. This is one 3.3 MB page for the whole book, not one page per chapter as for Socrates and Seneca. Please check once that jsDelivr renders it as a page on your machine (it did for the `.xhtml` files).

## 2. What the cleaning does

1. **Download** the one HTML file, cached in the raw folder.
2. **Keep only Montaigne's text:** the 16 letters, "To the Reader", and the 107 chapters of Books I–III. Hazlitt's preface and *Life*, the closing "Apology" note and Widger's "Editor's bookmarks" are skipped, as are chapter dedications printed as headings ("TO MADAME DIANE DE FOIX") and letter signatures ("Your humble servant, MONTAIGNE.").
3. **Remove editorial notes.** Hazlitt, Coste and Widger put their notes inline in square brackets, often between dashes: `three French gentlemen,—[These were Jean de Villemure ...]—who with incredible bravery`. Every bracketed note that is not a translation is removed (337 inline notes), with nested `{...}` notes and `(... D.W.)` remarks. Some editors' notes are themselves in quotation marks (Coste's, often starting "Montaigne ..."); those are recognised by the editor's name or by naming Montaigne in the third person, and removed too.
4. **Replace foreign quotations by their English translation.** Montaigne quotes Latin (and some Greek, Italian and French) constantly; this edition prints the original and then an English translation in brackets. The pipeline keeps only the English:
   - verse blocks (1,212): `“Diriguisse malis,” [“Petrified with her misfortunes.”—Ovid, Met., vi. 304.]` becomes `“Petrified with her misfortunes.”`; the citation is dropped. In the *Apology for Raimond Sebond* the layout is different (original, blank line, English), and is handled too.
   - inline quotations: `“Curae leves loquuntur, ingentes stupent.” [“Light griefs can speak ...”]` becomes the English sentence alone; italic Latin in the *Apology* (`<i>Satius est supervacua discere, quam nihil.</i> “'Tis better to learn ...”`) loses the italic part.
   - untranslated foreign quotations are dropped (88 inline; 92 of the 1,212 blocks yield no text, either untranslated verse, some of which the 19th-century translators refused to translate, or an editor's note printed as a block). English quotations are always kept. The language test is a small word-list heuristic (`is_foreign` / `is_english`); a scan of the output finds no remaining Latin sentence of three or more words.
5. **Split into paragraphs.** Each paragraph is one record in `turns.jsonl`. A verse quotation is joined to the paragraph before it, and so is the next paragraph when it continues the sentence (it starts in lower case).
6. **Flag sensitive content** (section 4).
7. **Write** `turns.jsonl`, `rag_passages.jsonl`, `montaigne_sft.jsonl`, `caution_candidates.csv` and `stats.json`.

`section` is exact and never crosses a boundary:

- Essays: book, chapter and title, e.g. `Book I, Chapter XIX: That to Study Philosophy Is to Learn to Die` (titles converted from capitals; typos in the source headings fixed in `TITLE_FIXES`), plus `To the Reader`.
- Letters: `Letter I: To Monsieur de Montaigne`.

## 3. Essays are not dialogues: turns and SFT

**Turns.** Montaigne is the only author, so a "turn" is one paragraph: `kind: speech`, `attribution: explicit`, `speaker: Montaigne`. Letters carry `addressee` (his father, his wife, the Jurats of Bordeaux, King Henry IV ...); the Essays have no addressee except "To the Reader". The *Apology for Raimond Sebond* (Book II, Chapter XII) is about 15% of the book on its own (531 passages).

**SFT: objection and reply.** As for Seneca, the only real conversational moves are the objections Montaigne puts in the reader's mouth. Unlike Seneca, Cotton usually prints them *without* quotation marks ("What matter is it, you will say, which way it comes to pass ...?"), and Montaigne uses the device rarely. The pipeline finds both quoted and unquoted objections (cues: *you will say / tell me / object*, *some one will say*, *it will be said*, *it may be objected*). "says one" / "says another" are not cues, because Montaigne uses them for poets and ancients, and neither is "if you say".

This gives only **6 examples** (5 train / 1 eval), for example:

```json
{"messages": [
  {"role": "system", "content": "You are Michel de Montaigne, the sixteenth-century French essayist, talking with a friend. ..."},
  {"role": "user", "content": "Reader: There is vanity in this way of living."},
  {"role": "assistant", "content": "But where is there not? All these fine precepts are vanity, and all wisdom is vanity: ..."}],
 "meta": {"work": "Essays", "work_id": "essays", "section": "Book III, Chapter IX: Of Vanity",
          "attribution": "tagged", "source": "objection", "split": "train", "...": "..."}}
```

That is expected for an essayist; the persona relies on the RAG passages at run time (ADR-03), and the SFT file is for few-shot examples and evaluation. Seneca's file was enlarged with 20 hand-rewritten reported questions; Montaigne has no correspondent whose questions he reports, so nothing similar was added.

**Optional topic prompts** (`--with-topic-prompts`, off by default): one example per essay, user = `Reader: Tell me what you think on this subject: Of Solitude.`, assistant = the opening of the essay (up to 200 words). The user line is written by us, so it is marked `attribution: synthetic_prompt`, `source: essay_topic`. With it the file has 109 examples.

**Split.** Every tenth chapter of each book (I.10, I.20, ..., II.10, II.20, II.30, III.10) is `eval`, whole, so neighbouring examples never land on both sides.

**System prompt.** It describes Montaigne's method rather than his conclusions (trying ideas on himself, weighing examples on both sides, admitting ignorance, leaving the other person freer to judge), in line with the team's focus on reasoning over conclusions.

## 4. Sensitive content

Montaigne writes about death throughout, discusses suicide at length (Book II, Chapter III, *A Custom of the Isle of Cea*, is an essay on it; also Cato in I.36 and II.13, the wives in II.35, I.19 *That to Study Philosophy Is to Learn to Die*), describes his kidney stones and pain in detail (II.37, III.13), and III.5 *Upon Some Verses of Virgil* is largely about sex and marriage. The content stays in the corpus (team decision of 2026-10-14) and is flagged:

| Flag | Passages (of 3,490) | How it is set |
|---|---|---|
| `suicide` | 104 | Regex for explicit wording in Cotton's English ("kill himself", "despatch himself", "throw themselves headlong", "voluntary death", "hasten our end", "starved himself", ...). All passages of II.3 get it regardless, since many of them speak of "the door" or "making one's exit". |
| `suicide_context` | 355 | Passages within two passages of a `suicide` passage in the same chapter, plus every passage of II.3, I.19, I.36, II.13 and II.35 (read by hand). Seneca's pipeline flags whole sections; Montaigne's chapters are much longer, and a section-level flag would have covered 2,000+ passages, most of them unrelated. The 31 sections that contain at least one flagged passage are listed in `stats.json`. |
| `death` | 582 | as for Socrates |
| `illness` | 458 | new: the stone, colic, disease, physicians, pain. Broad on purpose (Montaigne's view of doctors is a frequent topic); useful mainly to spot the kidney-stone passages. |
| `grief` | 76 | grief, mourning, sorrow (I.2 *Of Sorrow*, the death of La Boétie) |
| `violence` | 199 | as for Seneca, plus massacre, torment, cannibals |
| `sexuality` | 56 | lovers, venery, adultery, cuckold |

Flags are hints for corpus analysis and for the persona config's tier-2 list; they are not a filter and are not part of the retrieval contract (design doc v0.2, section 7.1). `caution_candidates.csv` lists the 104 `suicide` passages with `chunk_id`, section, flags and an excerpt around the match, as for Epictetus, as a starting point for Christopher's `cautions_against` list. A few are false positives (a dying man praying "if it be decreed in heaven that I am now to end my life"), so the list is worth a read before it goes into the config.

## 5. Output files

| File | Size | Purpose |
|---|---|---|
| `turns.jsonl` | 2,280 paragraphs (63 from the letters) | Base data: work, section, speaker, addressee, sensitive, text |
| `rag_passages.jsonl` | 3,490 passages of at most 180 words | For the vector store. Same fields as Seneca (`id`, `work_id`, `author`, `work`, `translator`, `section`, `turn_range`, `speakers`, `montaigne_words`, `speaker_uncertain` (always false), `addressee`, `sensitive`, `source_url`, `text`) |
| `montaigne_sft.jsonl` | 6 examples (5 train / 1 eval) | Chat format, Montaigne as the assistant |
| `caution_candidates.csv` | 104 rows | `suicide` passages for review |
| `stats.json` | — | Pinned commit, counts per work, flag counts, cleaning counts, suicide-context sections |

About 469k words of Montaigne: 457k from the Essays and 12k from the letters. Passage `id` is `<work_id>-<first 8 hex of SHA-256 of the text>`, so `chunk_id` is `montaigne-<work_id>-<8hex>`, e.g. `montaigne-essays-20596ac8`, `montaigne-letters-31d0e9fd`. Work ids: `essays`, `letters`.

## 6. Checked here

- 17 unit tests pass (front matter and end matter skipped, letter signature and notes removed, verse and inline translations, the Apology layout, italic Latin, lower-case continuation joins, chapter anchors in `source_url`, title fixes, quoted and unquoted objections, the eval split, stable content-hash ids, passage size, the suicide-context window).
- A scan of all output for leftover brackets, braces, editor names (Coste, Widger, "D.W.", Cotton) and Latin sentences of three or more words finds none (one false alarm: "Pope Julius II.").
- `build_sqlite.py build --persona montaigne --embed --model hash` loads all 3,490 passages, 2,280 turns and 6 SFT examples, and `retrieval.retrieve("montaigne", ...)` returns chunks with exactly the seven contract fields. The real all-MiniLM-L6-v2 model was not run here (no access to Hugging Face), so build with `--embed` on your Mac.
- `min_score` was calibrated on Socrates only; it is worth re-running `calibrate_min_score.py` with a few Montaigne questions.

## 7. Known limitations

- Cotton writes 17th-century English ("'tis", "peradventure", "betwixt"); making the voice casual is the plain-language layer's job.
- The foreign-language test is a heuristic. A short Latin phrase with no common Latin word ("Mus in pice") can stay in; a short English quotation is never dropped.
- Montaigne's sentences are very long. Passages are cut at sentence ends, or at a semicolon or colon when one sentence alone is over 180 words; 42 passages are under 30 words (ends of short chapters).
- Some objections run over two sentences ("Your rule is true enough as to what concerns death; but what will you say of indigence?"); the pipeline keeps only the first part as the user turn.
- One HTML page for the whole book means `source_url` relies on anchors; a citation opens the full 3.3 MB page.
