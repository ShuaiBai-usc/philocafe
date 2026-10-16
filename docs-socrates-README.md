# Socrates corpus cleaning

Public-domain corpus and cleaning code for the Philocafe Socrates persona. Uses only the Python standard library; nothing to install.

```bash
cd socrates-data
python3 socrates_pipeline.py --out output                    # 23 Plato dialogues
python3 socrates_pipeline.py --out output --with-xenophon    # plus 4 Xenophon works (needs access to gutenberg.org)
python3 -m unittest discover -s tests                        # unit tests
```

`output/` already holds the results of one full run (Plato only).

## 1. Sources and copyright

| Work | Translator / edition | Copyright status | Used |
|---|---|---|---|
| Plato, Dialogues (23 dialogues incl. Apology, Crito, Phaedo, Meno, Republic) | Benjamin Jowett, 3rd ed. 1892 | Jowett died 1893: **public domain worldwide**. Taken from [Standard Ebooks](https://github.com/standardebooks/plato_dialogues_benjamin-jowett), a proofread edition of the Project Gutenberg Jowett texts; markup is CC0 | ✅ default |
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

1. **Download**, cached in `output/raw/`; reruns do not download again.
2. **Remove everything that is not dialogue:** Jowett's long introductions, the list of persons, scene notes, endnotes and footnote markers in the text; Gutenberg header/footer, licence, table of contents, `[Footnote …]` blocks and `(1)`-style notes.
3. **Split by speaker**, with one of four modes per work:
   - **Drama** (14 works incl. Euthyphro, Meno, Gorgias, Theaetetus): speakers are labelled in the source, so the split is exact (`attribution: explicit`).
   - **Narrated by Socrates** (Republic, Charmides, Lysis, Protagoras, Euthydemus): speakers come from cues such as "I said / he replied" (`tagged`); paragraphs without a cue are inferred from turn alternation and direct address (`inferred`).
   - **Narrated by someone else** (Phaedo, Symposium, Parmenides): only the labelled frame is split; the rest is kept as narration and goes to the RAG passages only.
   - **Monologue** (Apology): the whole text is Socrates speaking.
4. **Write** three JSONL files and a stats file.

Laws has no Socrates and is skipped by default. In Sophist, Statesman, Timaeus and Critias Socrates is a minor speaker; they are kept and tagged. Use `--main-only` to keep only the works Socrates leads.

## 3. Output files

| File | Size | Purpose |
|---|---|---|
| `turns.jsonl` | 15,965 turns | Base data: work, section, speaker, `attribution` (confidence), text for every turn |
| `rag_passages.jsonl` | 1,453 passages of ~250 words | For the vector store, with citations; supports checking that the persona only quotes retrieved text |
| `socrates_sft.jsonl` | 3,297 examples | Chat format (system / user / assistant) with Socrates as the assistant. Usable as few-shot style examples or an eval set, and ready for fine-tuning later |
| `stats.json` | — | Per-work turn counts, word counts and attribution breakdown |

Socrates' own words total about 280k (about 500k for the whole corpus). 55% of the Socrates replies in the SFT examples end in a question, which fits the "questioner" persona.

Each passage in `rag_passages.jsonl` has a `sensitive` field flagging death, suicide, violence and sexuality. For example, the two Phaedo passages on "a philosopher is willing to die but must not take his own life" are flagged `suicide`, so the safety layer can treat them with care when they are retrieved.

One SFT example:

```json
{"messages": [
  {"role": "system", "content": "You are Socrates of Athens. You do not hand out answers..."},
  {"role": "user", "content": "Meno: But, Socrates, it is such a simple answer."},
  {"role": "assistant", "content": "Why simple?"},
  ...],
 "meta": {"work": "Meno", "turn_idx": 85, "attribution": "explicit", "is_question": false, "source_url": "..."}}
```

## 4. Known limitations

- **Speaker inference in narrated dialogues is not 100% accurate.** Checking the alternation rule against turns that carry explicit cues gives this agreement: Republic 96%, Protagoras 94%, Lysis 93%, Charmides 92%, Euthydemus 80%. So the SFT file **excludes** inferred turns by default; `--include-inferred` adds them (3,297 to 5,695 examples). When the interlocutor changes, the partner's name can lag for a few turns, but whether a turn is Socrates' is mostly right.
- The long narrated stretches of Phaedo, Symposium and Parmenides are not split into turns; they go to RAG only.
- Jowett writes 19th-century English. This only affects style; making the voice casual is the job of the proposal's plain-language layer.
- The four Gutenberg ids for Xenophon were not verified by downloading, because this environment cannot reach gutenberg.org. The code checks the downloaded title and skips the book with a warning if it does not match. Xenophon is narrative prose and goes to RAG only.

## 5. Layout

```
socrates-data/
  socrates_pipeline.py   cleaning code (work list and modes at the top of the file)
  tests/test_pipeline.py unit tests (including a Gutenberg-format sample)
  output/                run results + raw/ download cache
```
