# Seneca corpus cleaning

Public-domain corpus and cleaning code for the Philocafe Seneca persona. It follows the Socrates pipeline (`docs/socrates.md`, issue #2 fixes, design doc v0.2 retrieval contract) and writes the same files, so `build_sqlite.py` and `retrieval.py` work without changes. Python standard library only.

```bash
# from the philocafe/ repository root (script in scripts/, outputs git-ignored as for Socrates)
python3 scripts/seneca_pipeline.py                         # -> data/processed/seneca, cache in data/raw/seneca
python3 scripts/seneca_pipeline.py --with-topic-prompts    # also one templated example per letter
# scripts/seneca_reported_prompts.json must sit next to the script
python3 -m unittest discover -s scripts/tests              # unit tests

python3 scripts/build_sqlite.py build --persona seneca \
    --processed data/processed/seneca --db data/philocafe.db --embed
```

In this shared folder: `python3 seneca_pipeline.py --out output --raw output/raw` and `python3 -m unittest discover -s tests`. `output/` holds one full run.

## 1. Sources and copyright

| Work | Translator / edition | Copyright status | Used |
|---|---|---|---|
| Moral Letters to Lucilius (all 124 letters) | Richard M. Gummere, Loeb, 1917–1925 | **Public domain in the US** (published before 1930). Gummere died 1969, so the translation is still protected in life+70 countries (EU, UK) until the end of 2039. In China (life+50) it has been public domain since 2020. Same situation as Lamb's Plato in `docs/socrates.md`. | ✅ |
| Dialogues: On Providence, On the Firmness of the Wise Person, On Anger (3 books), To Marcia, On a Happy Life, On Leisure, On Peace of Mind, On the Shortness of Life, To Polybius, To Helvia, On Clemency (2 books), On Benefits (7 books) | Aubrey Stewart, 1887–1898 (Bohn's Classical Library) | Stewart died 1918: **public domain worldwide** | ✅ |
| Natural Questions; tragedies | various | Old translations exist but are not on Standard Ebooks; the tragedies are drama, not Seneca's own voice | ❌ |
| Modern translations (Campbell's *Letters from a Stoic*, Davie, Hadot, Graver & Long, Chinese translations) | — | Under copyright | ❌ |

Both texts come from Standard Ebooks (proofread transcriptions; markup is CC0), pinned to a commit and recorded in `stats.json`:

- `standardebooks/seneca_moral-letters-to-lucilius_richard-m-gummere` @ `f5bc9a76`
- `standardebooks/seneca_dialogues_aubrey-stewart` @ `b950b7cb`

`source_url` points to the same pinned file served by jsDelivr (one page per letter, one per essay), as for Socrates.

## 2. What the cleaning does

1. **Download** the 124 letter files and 12 essay files, cached in the raw folder; reruns do not download again. Introductions, appendices, endnotes, colophon and title pages are never downloaded.
2. **Remove what is not Seneca's prose:** footnote markers (1,070 in the Letters), the salutation ("Greetings from Seneca to his friend Lucilius"), every "Farewell." line, and the essays' dedications ("To Novatus."). Verse quotations (Virgil, Ovid, ...) and the paragraph that continues after them are joined into one paragraph.
3. **Split into paragraphs.** Each paragraph is one record in `turns.jsonl` (see section 3).
4. **Flag sensitive content** (section 4).
5. **Write** `turns.jsonl`, `rag_passages.jsonl`, `seneca_sft.jsonl` and `stats.json`.

`section` is exact and never crosses a boundary:

- Letters: the letter number and Gummere's title, e.g. `Letter LXX: On the Proper Time to Slip the Cable`.
- Essays in several books: `Book III, Chapter XV`. Single-book essays: `Chapter VI`.

## 3. Letters and essays are not dialogues: how turns and SFT are adapted

**Turns.** Seneca is the only author, so a "turn" is one paragraph. All turns are `kind: speech`, `attribution: explicit`, `speaker: Seneca`, with one exception: chapter I of *On Peace of Mind* is Serenus describing his own state of mind (Standard Ebooks marks it "(Serenus)"), so those paragraphs have `speaker: Serenus` and their RAG passages start with `Serenus: `. Seneca's own text carries no speaker label in passages. Turns also carry `addressee` (Lucilius, Novatus, Marcia, ...) and `sensitive`. Stewart often prints a whole chapter as one paragraph, so the essays have far fewer, longer turns than the Letters.

**SFT: objection and reply.** Seneca argues by putting objections in the mouth of an imagined interlocutor and answering them: *"'But,' you say, 'why should I not live with others?' Because the crowd harms the mind..."*. These are the only real conversational moves in the text, so each one becomes an example:

- `user`: the objection, prefixed `Lucilius:` in the Letters ("you say" there is Lucilius) and `Interlocutor:` in the essays (their "you" is often a generic opponent, e.g. an Epicurean in On Benefits IV, not the addressee). Split quotations are joined ("But why should I not ...?").
- `assistant`: Seneca's answer, the rest of the paragraph up to the next objection, extended into the next paragraph of the same section if it is under 15 words, and cut at a sentence end to at most 200 words (`--min-words`, `--max-words`).
- Only quotations with an objector cue count: *you say / ask / reply / object / will say*, *says our adversary / opponent / the objector*, *some one may say*, *it may be said*. "says he" is not a cue, because it usually introduces Epicurus or a poet.
- `meta` is the Socrates `meta` (`work`, `work_id`, `section`, `turn_idx`, `attribution: tagged`, `is_question`, `split`, `source_url`) plus `source: objection` and `sensitive`.

This gives **188 examples** (115 from the Letters, 38 from On Benefits, 16 from On Anger).

**SFT: reported questions (20 examples).** Seneca often reports what Lucilius wrote without quoting it ("You complain that you have met with an ungrateful person."; "You write me that you are anxious about the result of a lawsuit..."). These openings sound most like real users talking about their own lives. Their user turns were rewritten by hand into first person ("Lucilius: I have met with an ungrateful person.") and are stored in `seneca_reported_prompts.json` with the exact source sentence (`anchor`); the assistant turn is Seneca's text after the anchor, built as above. The rewrites add nothing that is not in the source, but they are not Seneca's or Gummere's words, hence `attribution: rewritten_report`, `source: reported`. `--no-reported` leaves them out.

**Total: 208 examples.** That is far fewer than Socrates' 3,184, which is expected for prose: most of Seneca is continuous exposition, and all of it is in the RAG passages, which is what the persona uses at run time. Since ADR-03 uses prompting + RAG only, the SFT file is meant for few-shot examples and evaluation. Self-posed question/answer sentence pairs (about 700) were tried and left out: many of them do not actually answer each other.

**Optional topic prompts** (`--with-topic-prompts`, off by default): one example per letter, user = `Lucilius: Write to me on this subject: On Saving Time.`, assistant = the opening of the letter. The user line is written by us, so it is marked `attribution: synthetic_prompt`, `source: letter_topic`. With it the file has 332 examples.

**Split.** Every tenth letter (X, XX, ... CXX) and three short essays (On Providence, On Leisure, To Helvia) are `eval`; the rest is `train`: 196 / 12. Splitting by whole letter or essay avoids leakage between neighbouring examples. The eval set is small; if you need more, add letters to `EVAL_LETTER_EVERY` or works to `EVAL_WORKS`.

## 4. Sensitive content

Seneca defends rational suicide openly (Letters LXX and LXXVII are about it; also Letters XII, XXIV, LVIII, LXXVIII, CXVII, On Providence VI, To Marcia XX and XXII), praises death as freedom, and writes three consolations to bereaved people. The content stays in the corpus (team decision of 2026-10-14) and is flagged:

| Flag | Passages (of 3,232) | How it is set |
|---|---|---|
| `suicide` | 53 | Regex for explicit wording plus Seneca's own metaphors ("slip the cable", "the door is open", "open one's veins", "path to freedom", "burst the bonds", "make an end of life"). All passages of Letters LXX and LXXVII get it regardless, because the regex misses their euphemisms ("the harbour", "take his departure"). |
| `suicide_context` | 282 | Every passage in a section where `suicide` matches at least once, plus three sections read by hand (Letter XXIV, To Marcia XX and XXII, On Anger III.15). The list of 24 sections is in `stats.json` (`suicide_context_sections`). This catches passages such as "Not to be born is the happiest lot" (To Marcia XXII) that do not name the act. |
| `grief` | 172 | grief, mourn, bereaved (new for Seneca; the Consolations) |
| `death` | 464 | as for Socrates |
| `violence` | 187 | as for Socrates, plus slaughter, crucifixion, the rack |
| `sexuality` | 82 | lovers, adultery, lust |

Flags are hints for corpus analysis and for the persona config's tier-2 list; they are not a filter and are not part of the retrieval contract (design doc v0.2, section 7.1). Some `suicide` matches are about other people or metaphors (Ajax in On Anger II.36, "strikes the sword from the hands of the suicide" in On Benefits III.9). The `suicide_context` list is the best starting point for Christopher's `cautions_against` list in the persona config: 16 of the 208 SFT examples come from these sections.

## 5. Output files

| File | Size | Purpose |
|---|---|---|
| `turns.jsonl` | 1,634 paragraphs (1,011 from the Letters) | Base data: work, section, speaker, addressee, sensitive, text |
| `rag_passages.jsonl` | 3,232 passages of at most 180 words | For the vector store. Same fields as Socrates (`id`, `author`, `work`, `translator`, `section`, `turn_range`, `speakers`, `seneca_words`, `speaker_uncertain` (always false), `sensitive`, `source_url`, `text`) plus `work_id` and `addressee` |
| `seneca_sft.jsonl` | 208 examples (196 train / 12 eval; 188 objection, 20 reported) | Chat format, Seneca as the assistant |
| `stats.json` | — | Pinned commits, counts per work, flag counts, list of suicide-context sections |

About 431k words of Seneca: 208k from the Letters and 223k from the essays (On Benefits alone 81k).

Passage `id` is `<work_id>-<first 8 hex of SHA-256 of the text>`, so `chunk_id` is `seneca-<work_id>-<8hex>`, e.g. `seneca-letters-e3add994`, `seneca-anger-4132c505`. Work ids contain no hyphen: `letters`, `providence`, `firmness`, `anger`, `marcia`, `happy_life`, `leisure`, `peace_of_mind`, `shortness_of_life`, `polybius`, `helvia`, `clemency`, `benefits`.

One SFT example (Letter LII):

```json
{"messages": [
  {"role": "system", "content": "You are Seneca, the Roman Stoic, writing to a friend. ..."},
  {"role": "user", "content": "Lucilius: But it is the fool who is inconsistent; nothing suits him for long."},
  {"role": "assistant", "content": "But how or when can we tear ourselves away from this folly? No man by himself has sufficient strength to rise above it; he needs a helping hand, and someone to extricate him."}],
 "meta": {"work": "Moral Letters to Lucilius", "work_id": "letters", "section": "Letter LII: On Choosing Our Teachers",
          "attribution": "tagged", "source": "objection", "split": "train", "...": "..."}}
```

## 6. Checked here

- 16 unit tests pass (parsing, salutation/Farewell/footnote removal, Serenus chapter, sections, objection extraction, reported prompts, SFT split, stable content-hash ids, passage size, curated section matching).
- `build_sqlite.py build --persona seneca --embed --model hash` loads all 3,232 passages, 1,634 turns and 208 SFT examples into a database next to Socrates, and `retrieval.retrieve("seneca", ...)` returns chunks with exactly the seven contract fields. The real all-MiniLM-L6-v2 model was not run here (no access to Hugging Face), so build with `--embed` on your Mac.
- `min_score` was calibrated on Socrates only; Seneca's longer prose passages may score differently, so it is worth re-running `calibrate_min_score.py` with a few Seneca questions.

## 7. Known limitations

- Gummere's translation is US public domain only (section 1).
- Objection detection needs quotation marks and a cue. Unquoted objections are only covered where they were rewritten by hand (`seneca_reported_prompts.json`), so the SFT set is small but precise.
- Passages are cut at sentence ends inside a section; the last passage of a short chapter can be short (68 passages are under 30 words).
- Gummere and Stewart write early-20th- and 19th-century English; making the voice casual is the plain-language layer's job.
