# Schopenhauer corpus cleaning

Public-domain corpus and cleaning code for the Philocafe Schopenhauer persona. It follows the Seneca pipeline (`docs/seneca.md`), the Socrates pipeline (`docs/socrates.md`, issue #2 fixes) and the design doc v0.2 retrieval contract, and writes the same files, so `build_sqlite.py` and `retrieval.py` work without changes. Python standard library only.

```bash
# from the philocafe/ repository root (script in scripts/, outputs in data/processed/schopenhauer)
python3 scripts/schopenhauer_pipeline.py                  # -> data/processed/schopenhauer, cache in data/raw/schopenhauer
python3 -m unittest discover -s scripts/tests -p 'test_schopenhauer*'

python3 scripts/build_sqlite.py build --persona schopenhauer \
    --processed data/processed/schopenhauer --db data/philocafe.db --embed
```

In this shared folder: `python3 schopenhauer_pipeline.py --out output --raw output/raw` and `python3 -m unittest discover -s tests`. `output/` holds one full run.

## 1. Sources and copyright

| Work | Translator / edition | Copyright status | Used |
|---|---|---|---|
| *The World as Will and Idea*, 3 vols (incl. the Appendix "Criticism of the Kantian Philosophy" and all 50 chapters of Supplements) | R. B. Haldane and J. Kemp, 1883–1886 (1909 reprint) | Published before 1930: **public domain in the US**. Haldane died 1928; we could not confirm Kemp's dates, so for life+70 countries treat it as "very likely" public domain rather than certain. | ✅ |
| Seven volumes of essays from *Parerga and Paralipomena*: *The Wisdom of Life*, *Counsels and Maxims*, *Studies in Pessimism*, *The Art of Controversy*, *The Art of Literature*, *On Human Nature*, *Religion: A Dialogue, Etc.* | T. Bailey Saunders, 1889–1896 | Saunders died 1928: **public domain worldwide** | ✅ |
| *On the Fourfold Root*, *On the Will in Nature*, *On the Basis of Morality*, *Essay on the Freedom of the Will* | various 19th-century translators | Not available from a source this sandbox can reach | ❌ |
| Modern translations (Payne, Norman/Welchman/Janaway, Aquila, Chinese translations) | — | Under copyright | ❌ |

**Standard Ebooks has no Schopenhauer release yet** (both titles are on its "wanted" list), and gutenberg.org is blocked here. The texts therefore come from **GITenberg**, a GitHub mirror of Project Gutenberg, as plain text at pinned commits (recorded in `stats.json`):

| Work id | Repository (github.com/GITenberg/...) | Commit |
|---|---|---|
| `wwi` vol. I | `The-World-As-Will-And-Idea--Vol.-1-of-3-_38427` | `153d1323` |
| `wwi` vol. II | `The-World-As-Will-And-Idea--Vol.-2-of-3-_40097` | `ea47b6cf` |
| `wwi` vol. III | `The-World-As-Will-And-Idea--Vol.-3-of-3-_40868` | `f17690ff` |
| `wisdom_of_life` | `The-Essays-of-Arthur-Schopenhauer--the-Wisdom-of-Life_10741` | `0d0f4906` |
| `counsels` | `The-Essays-of-Arthur-Schopenhauer--Counsels-and-Maxims_10715` | `1302cc71` |
| `pessimism` | `The-Essays-of-Arthur-Schopenhauer--Studies-in-Pessimism_10732` | `73e5702b` |
| `controversy` | `The-Essays-of-Arthur-Schopenhauer--the-Art-of-Controversy_10731` | `44620638` |
| `literature` | `The-Essays-of-Arthur-Schopenhauer--The-Art-of-Literature_10714` | `8e2bb98b` |
| `human_nature` | `The-Essays-of-Arthur-Schopenhauer--On-Human-Nature_10739` | `bff647e8` |
| `religion` | `The-Essays-of-Arthur-Schopenhauer--Religion-a-Dialogue-Etc._10833` | `c9b1195f` |

The underlying texts are public domain; the Project Gutenberg header and licence are removed (the licence allows this when the Gutenberg name is not used for the result). `source_url` points to the same pinned file on jsDelivr, as for Socrates and Seneca, but it is a **whole plain-text volume**, not one page per chapter, so the citation link opens the book and the `section` field says where to look. For the essays the link is the 7-bit ASCII edition of the same book, because jsDelivr serves `.txt` as UTF-8 and the Latin-1 file it was parsed from would show broken accents.

## 2. What the cleaning does

1. **Download** the ten text files (about 8 MB), cached in the raw folder.
2. **Remove what is not Schopenhauer's text:** the Gutenberg header and licence; the translators' prefaces (everything before Saunders' "T.B.S." signature, the Haldane/Kemp "Translators' Preface"); all footnotes, both Saunders' `[Footnote 1: ...]` blocks and inline `[Footnote: ...]`, and the WWI endnotes after "FOOTNOTES"; footnote markers (`[1]`, `word,(12)`); illustrations and figure captions; the translators' Abstract of the Fourfold Root and the Index at the end of vol. III; the dated signatures of the prefaces; headings such as "First Aspect" or "First Half". Underscore italics are removed and `--` becomes an em dash. Greek given only in transliteration (`[Greek: ...]`) becomes `[Greek]`.
3. **Quotations:** indented verse or prose quotations (and their "—GOETHE." attribution lines) are joined to the paragraph before them. A quotation that opens a section is a motto and is dropped.
4. **Split into paragraphs**, one record per paragraph in `turns.jsonl`.
5. **Flag sensitive content** (section 4) and write `turns.jsonl`, `rag_passages.jsonl`, `schopenhauer_sft.jsonl`, `caution_candidates.csv` and `stats.json`.

`section` is exact and never crosses a boundary:

- WWI vol. I: `Preface to the First Edition`, `Fourth Book: The World as Will, § 69` (one section per numbered §).
- WWI vols. II–III: `Appendix: Criticism of the Kantian Philosophy`, `Supplements to the Fourth Book, Chapter XLVI: On the Vanity and Suffering of Life`. Turns and passages also carry `volume` ("I", "II", "III").
- Essays: the essay title (`On Suicide`, `Of Women`, `Immortality: A Dialogue`), with chapters and numbered sections where the book has them (`Chapter III: Our Relation to Others, Section 29`, `Chapter IV: Position, or a Man's Place in the Estimation of Others, Section 4: Honor`, `The Art of Controversy, Stratagem XXIX`).

## 3. Turns and SFT

**Turns.** Most of Schopenhauer is continuous prose, so a "turn" is one paragraph, `kind: speech`, `attribution: explicit`, `speaker: Schopenhauer`. Two essays are real dialogues, and there the speaker is named: *Religion: A Dialogue* (Demopheles and Philalethes) and *Immortality: A Dialogue* (Thrasymachos and Philalethes). Philalethes ("lover of truth") is Schopenhauer's spokesman, so his words count towards `schopenhauer_words`; in passages every dialogue line starts with its speaker (`Demopheles: ...`, `Philalethes: ...`), while Schopenhauer's own prose carries no label. The Subject/Matter exchange in WWI vol. II, chapter I keeps its labels inside the text.

**SFT (38 examples).** Most of the 38 come from the two dialogues: the interlocutor's turn is the user (`Demopheles: ...`, `Thrasymachos: ...`), Philalethes' next turn is the assistant (cut at a sentence end to at most 200 words; replies under 4 words and stage asides like "(Aside.) German humbug, he means." are skipped). That gives 37 pairs, plus 1 objection/reply pair found with the Seneca method (`Interlocutor: The world is God.` from *A Few Words on Pantheism*).

This is far fewer than Seneca's 208, and that is expected. Schopenhauer almost never answers an imagined "you say" objection. Where he does quote someone ("of which it may be said: 'It is bad to-day, and it will be worse to-morrow'", "any one might reply: 'I wish I had been left in the peace of the all-sufficient nothing'"), the quote is a lament he goes on to develop, not an objection he answers. Using those would teach the persona to elaborate despair, so the `it may be said` / `one might reply` cues from the Seneca pipeline are left out on purpose. Since ADR-03 is prompting + RAG only, the SFT file is for few-shot examples and evaluation; the RAG passages are what the persona uses at run time. Seneca-style hand-rewritten prompts (`seneca_reported_prompts.json`) could be added later if more examples are needed.

**Split.** The whole Immortality dialogue is `eval` (6 examples), the rest is `train` (32). Objection examples from every tenth section of a work would also be `eval`, but the one objection example is not in such a section.

`meta` is the Seneca `meta` (`work`, `work_id`, `section`, `turn_idx`, `attribution`, `source` = `dialogue` / `objection`, `is_question`, `sensitive`, `split`, `source_url`) plus `speaker`.

## 4. Sensitive content

Schopenhauer is the most pessimistic author in the project. He calls suffering the positive element of life and happiness merely its absence, says non-existence would be preferable to existence, and devotes *On Suicide* (Studies in Pessimism) and WWI § 69 to suicide. He argues *against* suicide (it affirms the will instead of denying it), but he also defends it against religious condemnation. The essay *Of Women* and remarks on Jews and "savages" are plain prejudice. Following the team decision of 2026-10-14, all of it stays in the corpus and is flagged:

| Flag | Passages (of 5,306) | How it is set |
|---|---|---|
| `suicide` | 57 | Regex for explicit wording (suicide, take one's own life, lay hands on oneself, voluntary death, starve oneself, ...). All passages of *On Suicide* and WWI § 69 get it regardless. |
| `suicide_context` | 349 | Passages up to 2 before and after a `suicide` passage in the same section, plus every passage of four sections read by hand: *On the Sufferings of the World*, *The Vanity of Existence*, WWI chapters XLVI (On the Vanity and Suffering of Life) and XLVIII (On the Denial of the Will to Live). Unlike Seneca the flag does not spread over a whole section, because Schopenhauer's sections are long (a WWI chapter or "Psychological Observations" runs to thousands of words) and section-wide flagging marked over 1,100 passages, most of them unrelated. The 25 sections with at least one flag are in `stats.json` (`suicide_context_sections`). |
| `despair` | 50 | New for Schopenhauer: lines that devalue life itself ("better not to be", "non-existence would be preferable", "misery / worthlessness / vanity of existence", "weariness of life", "despair", "hopeless"). His doctrine of suffering is everywhere, so this pattern is deliberately narrow. |
| `prejudice` | 137 | New: all of *Of Women*, plus mentions of Jews / Judaism, "negroes", "savages", "the fair sex", "woman is by nature ...". Many of the Judaism mentions criticise Jewish theology rather than insult people, but some are contemptuous ("a small, isolated, ... obscure people"), so the flag is for review, not a verdict. |
| `death` | 462 | as for Socrates |
| `violence` | 100 | as for Seneca, plus cruelty |
| `grief` | 40 | as for Seneca |
| `sexuality` | 162 | as for Seneca, plus the sexes, procreation (WWI ch. XLIV, The Metaphysics of the Love of the Sexes) |

Flags are hints for corpus analysis and for the persona config's tier-2 list; they are not a filter and not part of the retrieval contract (design doc v0.2, section 7.1).

**`caution_candidates.csv` (497 rows)** lists every passage flagged `suicide`, `suicide_context`, `despair` or `prejudice`, as a starting point for Christopher's `cautions_against` list in the persona config (keyed by `chunk_id`). Columns: `chunk_id`, `priority`, `work`, `volume`, `section`, `flags`, `excerpt` (first 200 characters). `priority` is `high` (102 rows) when the passage itself names suicide or devalues life, and `medium` (395) when it only sits next to such a passage or is flagged for prejudice. The system prompt in the SFT file also tells the persona to describe suffering honestly but never to urge anyone towards despair or self-harm.

## 5. Output files

| File | Size | Purpose |
|---|---|---|
| `turns.jsonl` | 3,030 paragraphs (1,351 from WWI) | Base data: work, volume, section, speaker, sensitive, text |
| `rag_passages.jsonl` | 5,306 passages of at most 180 words (3,585 from WWI) | For the vector store. Same fields as Seneca (`id`, `work_id`, `author`, `work`, `translator`, `section`, `turn_range`, `speakers`, `schopenhauer_words`, `speaker_uncertain` (always false), `sensitive`, `source_url`, `text`) with `volume` in place of `addressee` |
| `schopenhauer_sft.jsonl` | 38 examples (32 train / 6 eval) | Chat format, Schopenhauer (Philalethes) as the assistant |
| `caution_candidates.csv` | 497 rows | See section 4 |
| `stats.json` | — | Pinned commits, counts per work, flag counts, suicide-context sections |

About 730k words of Schopenhauer: 508k from *The World as Will and Idea* and 223k from the seven essay volumes.

| Work id | Work | Sections | Paragraphs | Words |
|---|---|---|---|---|
| `wwi` | The World as Will and Idea | 124 | 1,351 | 507,680 |
| `wisdom_of_life` | The Wisdom of Life | 9 | 197 | 35,958 |
| `counsels` | Counsels and Maxims | 55 | 351 | 42,452 |
| `pessimism` | Studies in Pessimism | 9 | 234 | 29,139 |
| `controversy` | The Art of Controversy (with Psychological Observations, Aphorisms, Genius and Virtue) | 44 | 261 | 27,864 |
| `literature` | The Art of Literature | 8 | 266 | 33,822 |
| `human_nature` | On Human Nature | 6 | 207 | 31,484 |
| `religion` | Religion: A Dialogue, Etc. | 6 | 163 | 27,880 |

Passage `id` is `<work_id>-<first 8 hex of SHA-256 of the text>`, so `chunk_id` is `schopenhauer-<work_id>-<8hex>`, e.g. `schopenhauer-wwi-daf7a5b3`, `schopenhauer-pessimism-…`. Work ids contain no hyphen.

One SFT example (Religion: A Dialogue):

```json
{"messages": [
  {"role": "system", "content": "You are Arthur Schopenhauer, talking with someone who wants to think a question through. ..."},
  {"role": "user", "content": "Demopheles: That may be, but still for a man who hasn't a natural leg, a wooden one is of great service. ..."},
  {"role": "assistant", "content": "That is certainly the strong point of religion. If it is a fraud, it is a pious fraud; that is undeniable. ..."}],
 "meta": {"work": "Religion: A Dialogue, Etc.", "work_id": "religion", "section": "Religion: A Dialogue",
          "attribution": "explicit", "source": "dialogue", "speaker": "Philalethes", "split": "train", "...": "..."}}
```

## 6. Checked here

- 16 unit tests pass (Gutenberg header/licence and translator-note removal, footnotes, quotations and mottos, dashes and italics, dialogue speakers, Counsels chapters and inline sections, WWI § and chapter headings, footnote markers, the translators' appendix cut, title case, flags, dialogue SFT pairs and asides, objection cues, stable content-hash ids, passage size, suicide-context window, caution CSV).
- `build_sqlite.py build --persona schopenhauer --embed --model hash` (retrieval v0.2 package) loads all 5,306 passages, 3,030 turns and 38 SFT examples, and `retrieval.retrieve("schopenhauer", ...)` returns chunks with exactly the seven contract fields. The real all-MiniLM-L6-v2 model was not run here (no access to Hugging Face), so build with `--embed` on your Mac.
- Sections, chapter titles and paragraph boundaries were spot-checked against the source files.

## 7. Known limitations

- **WWI is about two thirds of all passages**, and it is dense, technical writing (the Kantian Criticism alone is 53k words in one section). Questions about everyday life will usually match the essays better; if the persona's retrieval leans too much on WWI, a persona-level filter or a lower weight for `wwi` is an option. `--works` builds a subset.
- The Gutenberg transcription of WWI vol. I has no heading for § 25; its text is inside `Second Book: The World as Will, § 24`.
- `source_url` opens a whole volume, not a chapter (section 1).
- Plain-text sources have no markup, so headings are recognised from layout (all-caps lines, "Chapter XLVI.", "§ 12.") and a per-book list of essay titles in `ESSAYS`. A new edition of a source file needs those lists checked again.
- Tables and diagrams in WWI (e.g. the "Prædicabilia a priori" table in vol. II, ch. IV) come out as flat text.
- Haldane/Kemp and Saunders write 19th-century English; making the voice casual is the plain-language layer's job.
- `min_score` was calibrated on Socrates only; re-run `calibrate_min_score.py` with a few Schopenhauer questions after the real-embedding build.
