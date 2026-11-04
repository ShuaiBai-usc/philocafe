#!/usr/bin/env python3
"""Philocafe · Epictetus corpus pipeline.

Downloads public-domain Epictetus texts, strips everything that is not
Epictetus' teaching (translator introductions, Arrian's preface, endnotes,
footnote markers, Greek glosses, Latin and Greek fragments), splits the texts
into paragraph turns and writes:

  turns.jsonl               one record per paragraph (all works)
  rag_passages.jsonl        passages of at most ~180 words with citations, for retrieval
  caution_candidates.csv    passages flagged `suicide`, for review of the persona's
                            tier-2 caution list (keyed by chunk_id)
  stats.json                per-work counts and the pinned source commits

No SFT file is written: Epictetus' works are lectures and maxims, not
dialogues, so there is no real user turn to pair with his words (see
docs/epictetus.md).

Sources (see docs/epictetus.md for copyright notes), both tr. George Long
(1877), via Standard Ebooks (text is public domain, markup is CC0):
  * Discourses, Books I-IV (recorded by Arrian)
  * Short Works: the Enchiridion and the Fragments

Shared helpers come from socrates_pipeline.py, so the output schema matches
the Socrates corpus. Run from the repository root:

    python3 scripts/epictetus_pipeline.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path

from socrates_pipeline import (EPUB_TYPE, XHTML, Turn, el_text, fetch, norm,
                               split_words, write_jsonl)

# --------------------------------------------------------------------------
# Source configuration
# --------------------------------------------------------------------------

# Pinned to commits so that upstream proofreading changes cannot silently
# change the output. The commits are also recorded in stats.json.
SE_REPOS = {
    "discourses":  dict(repo="standardebooks/epictetus_discourses_george-long",
                        commit="a50e918ff19c48e94e274bf55ad3d8a5209e0471"),
    "short-works": dict(repo="standardebooks/epictetus_short-works_george-long",
                        commit="8c154d40a6f85e32a5711001a28c1b55ab56d3c8"),
}


def raw_url(repo_key: str, name: str) -> str:
    r = SE_REPOS[repo_key]
    return f"https://raw.githubusercontent.com/{r['repo']}/{r['commit']}/src/epub/text/{name}"


def read_url(repo_key: str, name: str, anchor: str) -> str:
    """Citation link shown to users: the pinned file served by jsDelivr, which
    sends it as XHTML so the browser renders it; the anchor is the chapter."""
    r = SE_REPOS[repo_key]
    return f"https://cdn.jsdelivr.net/gh/{r['repo']}@{r['commit']}/src/epub/text/{name}#{anchor}"


# kind:
#   discourse    lectures; Arrian sometimes frames a chapter ("When a man was
#                consulting him ..., Epictetus replied: ...")
#   manual       numbered chapters, all Epictetus (the Enchiridion)
#   fragments    numbered sayings collected by later anthologists; Long notes
#                that some are certainly not by Epictetus, so they are
#                "attributed", not "explicit"
WORKS = {
    "discourses":  dict(title="Discourses", repo="discourses", kind="discourse",
                        files=["book-1.xhtml", "book-2.xhtml", "book-3.xhtml", "book-4.xhtml"]),
    "enchiridion": dict(title="Enchiridion", repo="short-works", kind="manual",
                        files=["the-enchiridion.xhtml"]),
    "fragments":   dict(title="Fragments", repo="short-works", kind="fragments",
                        files=["fragments.xhtml"]),
}

PERSONA = "Epictetus"
NARRATOR = "Arrian"

# Passages touching on these themes are flagged for corpus analysis. Keys
# match the Socrates corpus. Epictetus defends leaving life when it becomes
# unbearable ("the door is open", "the smoke"), so `suicide` also matches his
# euphemisms; these passages need care in the persona config.
SENSITIVE_PATTERNS = {
    "suicide": r"\b(suicide|take (his|her|their|one's|my|your) own life|kill (him|her|my|your|them)sel(f|ves)"
               r"|lay violent hands|hang (yourself|himself|myself)|starve (himself|herself|yourself|myself)"
               r"|door (is|stands|ought to be) open|opens the door|is the door closed"
               r"|depart(s|ed)? from life|in your power to die|signal for retreat|(give|gives|sounds) the signal"
               r"|smoke is (moderate|excessive)|smoked no more|depart to the place from which)\b",
    "death": r"\b(death|dying|die|dies|died|corpse|hemlock|poison(ed)?|executed?|execution)\b",
    "violence": r"\b(murder(ed|er)?|slay|slain|beat(en)?|scourged?|tortur(e|ed)|whipp(ed|ing)"
                r"|beheaded|head cut off|the rack)\b",
    "sexuality": r"\b(lovers?|beloved|sexual|intercourse|embraces?|adulter(y|er|ers|ess)|catamites?)\b",
}

# Arrian's framing of an exchange. A colon tag splits a paragraph into
# narration and Epictetus' speech: "When a person was reading hypothetical
# arguments, Epictetus said: This also is ..."
TAG_VERBS = "said|replied|answered|asked|inquired|enquired|continued|added|rejoined"
FRAME_COLON = re.compile(rf"\b(Epictetus|he) ({TAG_VERBS})( to (him|them))?:\s*")
# "If a man, said Epictetus, opposes evident truths, ...": a tag inside his
# own first sentence, removed from the text.
INLINE_TAG = re.compile(rf"^([^.?!“”]{{1,80}}?),\s*({TAG_VERBS}) (Epictetus|he),\s*")
# Third-person mentions that mark a paragraph as Arrian's report
# ("Epictetus inquired of him", "said to him (Epictetus)").
THIRD_PERSON = re.compile(
    rf"\bEpictetus (being asked|was asked|{TAG_VERBS})\b"
    rf"|\b({TAG_VERBS}) Epictetus\b"
    r"|\((Epictetus)\)"
    r"|^(When|As|Some person|A certain person)\b.{0,200}\b(to him|him)\b.{0,40}\bEpictetus\b")

GREEK = r"[Ͱ-Ͽἀ-῿]"


@dataclass
class EpictetusTurn(Turn):
    chapter_title: str = ""   # Discourses only, e.g. "Of Natural Affection"


# --------------------------------------------------------------------------
# Text cleaning
# --------------------------------------------------------------------------


def strip_greek(text: str) -> str:
    """Remove Greek words that Long adds as glosses.

    "opinion (ὑπόληψις)" -> "opinion"; "aversion (ἔκκλισις, turning from a
    thing)" -> "aversion (turning from a thing)". English glosses such as
    "desire (aim at)" are Long's translation and are kept.
    """
    def paren(m: re.Match) -> str:
        inner = m.group(1)
        if not re.search(GREEK, inner):
            return m.group(0)
        inner = re.sub(rf"{GREEK}+([\s’'‘]+{GREEK}+)*", "", inner)
        inner = re.sub(r"^[\s,;:.]+|[\s,;:]+$", "", inner)
        return f" ({inner})" if re.search(r"[A-Za-z]", inner) else " "

    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\s*\(([^()]*)\)", paren, text)
    return norm(re.sub(r"\s+([,;:.?!])", r"\1", text))


def block_text(el: ET.Element) -> str:
    """Text of a blockquote: verse lines, or a quoted scene from a play
    ("Polynices: Where will you take your station ...")."""
    rows = []
    for tr in el.iter(XHTML + "tr"):
        tds = tr.findall(XHTML + "td")
        if len(tds) >= 2 and "persona" in tds[0].get(EPUB_TYPE, ""):
            rows.append(f"{el_text(tds[0])}: {el_text(tds[1])}")
    return " ".join(rows) if rows else el_text(el)


def iter_paragraphs(section: ET.Element):
    """Yield (text, continues_previous) for the body of one chapter."""
    for el in section:
        tag = el.tag.replace(XHTML, "")
        if tag in ("h2", "h3", "h4", "hgroup", "header"):
            continue
        if tag == "blockquote":
            yield block_text(el), True
        elif tag == "p":
            yield el_text(el), "continued" in (el.get("class") or "")


def is_english(el: ET.Element) -> bool:
    lang = el.get("{http://www.w3.org/XML/1998/namespace}lang", "en")
    return lang.startswith("en")


def chapter_title(sec: ET.Element) -> str:
    for p in sec.iter(XHTML + "p"):
        if p.get(EPUB_TYPE, "") == "title":
            return el_text(p)
    return ""


def chapter_number(sid: str) -> int:
    """"chapter-1-11" -> 11, "fragments-29" -> 29. The id is used because the
    heading can carry a footnote marker ("XXIX" + "49")."""
    return int(sid.rsplit("-", 1)[1])


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def split_frame(text: str) -> tuple[str, str] | None:
    """Split Arrian's framing from Epictetus' speech at a colon tag.

    Returns (narration, speech), or None if the paragraph has no frame. The
    tag is kept at the end of the narration so the passage still reads
    "..., Epictetus replied:" followed by the speech.
    """
    m = FRAME_COLON.search(text)
    if not m or m.end() >= len(text):
        return None
    before = text[:m.start()]
    # A frame is third-person narration: it names Epictetus or "him", and
    # does not open inside a quotation.
    if m.group(1) == "he" and not re.search(r"\b(him|Epictetus)\b", before):
        return None
    if before.count("“") > before.count("”"):
        return None
    if text[m.end():].startswith("“"):
        return None                   # a reported exchange in quotations
    return norm(text[:m.end()]), norm(text[m.end():])


def parse_work(work_id: str, meta: dict, files: dict[str, bytes]) -> list[EpictetusTurn]:
    turns: list[EpictetusTurn] = []
    base = dict(work_id=work_id, work=meta["title"], author=PERSONA, translator="George Long")
    kind = meta["kind"]

    def add(speaker, k, attribution, text, section, url, title):
        if text:
            turns.append(EpictetusTurn(**base, source_url=url, section=section, idx=len(turns),
                                       speaker=speaker, kind=k, attribution=attribution,
                                       text=text, chapter_title=title))

    for name in meta["files"]:
        root = ET.fromstring(files[name])
        book = None
        if kind == "discourse":
            m = re.fullmatch(r"book-(\d)\.xhtml", name)
            book = ("I", "II", "III", "IV")[int(m.group(1)) - 1]
        for sec in root.iter(XHTML + "section"):
            sid = sec.get("id", "")
            if kind == "discourse" and not sid.startswith("chapter-"):
                continue
            if kind != "discourse" and not re.fullmatch(rf"{re.escape(name[:-6])}-\d+", sid):
                continue                  # e.g. "fragments-introduction" (Long's)
            if not is_english(sec):
                continue                  # Latin and Greek fragments (CLXXVIII-CLXXXI)
            num = chapter_number(sid)
            if kind == "discourse":
                section = f"Book {book}, Chapter {num}"
            elif kind == "manual":
                section = f"Chapter {num}"
            else:
                section = f"Fragment {num}"
            title = chapter_title(sec) if kind == "discourse" else ""
            url = read_url(meta["repo"], name, sid)
            first = len(turns)
            for text, cont in iter_paragraphs(sec):
                text = strip_greek(text)
                if not text:
                    continue
                if cont and len(turns) > first:
                    prev = turns[-1]
                    prev.text = norm(prev.text + " " + text)
                    prev.words = len(prev.text.split())
                    continue
                if kind == "fragments":
                    add(PERSONA, "speech", "attributed", text, section, url, title)
                    continue
                if kind == "discourse":
                    frame = split_frame(text)
                    if frame:
                        add(NARRATOR, "narration", "narration", frame[0], section, url, title)
                        add(PERSONA, "speech", "tagged", frame[1], section, url, title)
                        continue
                    m = INLINE_TAG.match(text)
                    if m and not THIRD_PERSON.search(text[m.end():]):
                        add(PERSONA, "speech", "tagged", norm(m.group(1) + " " + text[m.end():]),
                            section, url, title)
                        continue
                    if THIRD_PERSON.search(text):
                        # Arrian reports a whole exchange in quotations
                        # (Of Natural Affection); not split into turns.
                        add(NARRATOR, "narration", "narration", text, section, url, title)
                        continue
                add(PERSONA, "speech", "explicit", text, section, url, title)
    return turns


# --------------------------------------------------------------------------
# Outputs
# --------------------------------------------------------------------------


def flag_sensitive(text: str) -> list[str]:
    return [k for k, pat in SENSITIVE_PATTERNS.items() if re.search(pat, text, re.I)]


def build_passages(turns: list[EpictetusTurn], target_words: int) -> list[dict]:
    """Group the turns of one chapter into passages of at most `target_words`
    words. Chapters are never merged, so every passage has one citation.

    Epictetus is the only speaker, so lines carry no speaker label.
    """
    passages = []
    buf: list[tuple[EpictetusTurn, str]] = []
    size = 0
    used: set[str] = set()

    def flush():
        if not buf:
            return
        lines: list[str] = []
        for j, (t, piece) in enumerate(buf):
            if j and buf[j - 1][0] is t:
                lines[-1] += " " + piece
            else:
                lines.append(piece)
        text = "\n".join(lines)
        f = buf[0][0]
        # Content-based id: stays the same when the corpus is rebuilt and turn
        # numbers shift; changes only when the passage text changes.
        pid, n = None, 0
        while pid is None or pid in used:
            salt = f"\0{n}" if n else ""
            pid = f"{f.work_id}-{hashlib.sha256((text + salt).encode('utf-8')).hexdigest()[:8]}"
            n += 1
        used.add(pid)
        passages.append({
            "id": pid,
            "author": f.author, "work": f.work, "translator": f.translator,
            "section": f.section, "chapter_title": f.chapter_title,
            "turn_range": [f.idx, buf[-1][0].idx],
            "speakers": sorted({t.speaker for t, _ in buf}),
            "epictetus_words": sum(len(p.split()) for t, p in buf if t.speaker == PERSONA),
            "speaker_uncertain": False,
            "attribution": sorted({t.attribution for t, _ in buf}),
            "sensitive": flag_sensitive(text),
            "source_url": f.source_url,
            "text": text,
        })
        buf.clear()

    for t in turns:
        if buf and (t.work_id != buf[0][0].work_id or t.section != buf[0][0].section):
            flush()
            size = 0
        for piece in split_words(t.text, target_words):
            n = len(piece.split())
            if buf and size + n > target_words:
                flush()
                size = 0
            buf.append((t, piece))
            size += n
    flush()
    return passages


def write_cautions(path: Path, passages: list[dict], persona: str = "epictetus") -> int:
    rows = [p for p in passages if "suicide" in p["sensitive"]]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["chunk_id", "work", "section", "chapter_title", "flags", "excerpt"])
        for p in rows:
            w.writerow([f"{persona}-{p['id']}", p["work"], p["section"], p["chapter_title"],
                        ",".join(p["sensitive"]), p["text"][:200].replace("\n", " ")])
    return len(rows)


def summarize(wt: list[EpictetusTurn]) -> dict:
    mine = [t for t in wt if t.speaker == PERSONA]
    attrs: dict[str, int] = {}
    for t in wt:
        attrs[t.attribution] = attrs.get(t.attribution, 0) + 1
    return {"turns": len(wt), "chapters": len({t.section for t in wt}),
            "epictetus_turns": len(mine),
            "epictetus_words": sum(t.words for t in mine),
            "total_words": sum(t.words for t in wt), "attribution": attrs}


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("data/processed/epictetus"))
    ap.add_argument("--raw", type=Path, default=Path("data/raw/epictetus"),
                    help="download cache (git-ignored)")
    ap.add_argument("--works", nargs="*", choices=list(WORKS), help="work ids to include (default: all)")
    ap.add_argument("--passage-words", type=int, default=180,
                    help="max words per RAG passage (the embedding model reads ~256 tokens)")
    args = ap.parse_args(argv)

    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    turns: list[EpictetusTurn] = []
    report = {}
    for wid, meta in WORKS.items():
        if args.works and wid not in args.works:
            continue
        try:
            files = {name: fetch(raw_url(meta["repo"], name), args.raw / meta["repo"] / name)
                     for name in meta["files"]}
            wt = parse_work(wid, meta, files)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {wid}: {e}", file=sys.stderr)
            continue
        # turn indices run per work, as in the Socrates corpus
        turns.extend(wt)
        report[wid] = summarize(wt)

    passages = build_passages(turns, args.passage_words)
    n_turns = write_jsonl(out / "turns.jsonl", (asdict(t) for t in turns))
    n_pass = write_jsonl(out / "rag_passages.jsonl", passages)
    n_caution = write_cautions(out / "caution_candidates.csv", passages)
    flags: dict[str, int] = {}
    for p in passages:
        for f in p["sensitive"]:
            flags[f] = flags.get(f, 0) + 1
    (out / "stats.json").write_text(json.dumps(
        {"source": {k: dict(v) for k, v in SE_REPOS.items()},
         "turns": n_turns, "passages": n_pass, "sft_examples": 0,
         "passage_flags": flags, "caution_candidates": n_caution,
         "max_passage_words": max((len(p["text"].split()) for p in passages), default=0),
         "works": report},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"turns={n_turns} passages={n_pass} caution_candidates={n_caution} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
