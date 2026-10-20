#!/usr/bin/env python3
"""Philocafe · Socrates corpus pipeline.

Downloads public-domain Socratic texts, strips everything that is not the
dialogue itself (translator introductions, endnotes, footnote markers,
Gutenberg boilerplate), splits the dialogues into speaker turns, and writes
three JSONL files:

  turns.jsonl         one record per speaker turn (all works)
  socrates_sft.jsonl  chat-format examples where Socrates is the assistant
  rag_passages.jsonl  passages of at most ~180 words with citations, for retrieval

Sources (see docs/socrates.md for copyright notes):
  * Plato, Dialogues, tr. Benjamin Jowett, via Standard Ebooks
    (proofread edition of the Project Gutenberg Jowett texts; text is public
    domain, Standard Ebooks markup is CC0).
  * Optional: Xenophon's Socratic works, tr. H. G. Dakyns, via Project
    Gutenberg plain text (--with-xenophon). These are narrated, so they go
    to rag_passages only.

Only the Python standard library is used. Run from the repository root:

    python3 scripts/socrates_pipeline.py
    python3 scripts/socrates_pipeline.py --with-xenophon --include-inferred
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from pathlib import Path

# --------------------------------------------------------------------------
# Source configuration
# --------------------------------------------------------------------------

# Pinned to a commit so that upstream proofreading changes cannot silently
# change the output. The commit is also recorded in stats.json.
SE_REPO = "standardebooks/plato_dialogues_benjamin-jowett"
SE_COMMIT = "2420758c289891438b0099019cfc7d3108b5062c"
SE_BASE = f"https://raw.githubusercontent.com/{SE_REPO}/{SE_COMMIT}/src/epub/text/"
# Citation link shown to users: the same pinned file served by jsDelivr, which
# sends it as XHTML so the browser renders the text instead of the markup.
SE_READ_BASE = f"https://cdn.jsdelivr.net/gh/{SE_REPO}@{SE_COMMIT}/src/epub/text/"

# mode:
#   drama        speakers are labelled ("Socrates: ..."); unlabelled paragraphs
#                continue the previous speaker
#   narrated     Socrates narrates in the first person ("I said", "he replied");
#                speakers are inferred from attribution tags and alternation
#   frame_only   labelled frame, then someone other than Socrates narrates;
#                only labelled turns are split, the rest is kept as narration
#   monologue    a single speech by Socrates; `exchanges` marks stretches where
#                he questions someone and their short answers are interleaved
# socrates_role: main | minor | absent (absent works are skipped by default)
PLATO_WORKS = {
    "euthyphro":  dict(title="Euthyphro",  mode="drama",      socrates_role="main"),
    "apology":    dict(title="Apology",    mode="monologue",  socrates_role="main",
                       exchanges=[dict(start=r"Come hither, Meletus",
                                       end=r"I have said enough in answer to the charge of Meletus",
                                       partner="Meletus")]),
    "crito":      dict(title="Crito",      mode="drama",      socrates_role="main"),
    "phaedo":     dict(title="Phaedo",     mode="frame_only", socrates_role="main", narrator="Phaedo"),
    "charmides":  dict(title="Charmides",  mode="narrated",   socrates_role="main"),
    "laches":     dict(title="Laches",     mode="drama",      socrates_role="main"),
    "lysis":      dict(title="Lysis",      mode="narrated",   socrates_role="main"),
    "euthydemus": dict(title="Euthydemus", mode="narrated",   socrates_role="main"),
    "protagoras": dict(title="Protagoras", mode="narrated",   socrates_role="main"),
    "gorgias":    dict(title="Gorgias",    mode="drama",      socrates_role="main"),
    "meno":       dict(title="Meno",       mode="drama",      socrates_role="main"),
    "ion":        dict(title="Ion",        mode="drama",      socrates_role="main"),
    "cratylus":   dict(title="Cratylus",   mode="drama",      socrates_role="main"),
    "symposium":  dict(title="Symposium",  mode="frame_only", socrates_role="main", narrator="Apollodorus"),
    "republic":   dict(title="Republic",   mode="narrated",   socrates_role="main"),
    "phaedrus":   dict(title="Phaedrus",   mode="drama",      socrates_role="main"),
    "theaetetus": dict(title="Theaetetus", mode="drama",      socrates_role="main"),
    "philebus":   dict(title="Philebus",   mode="drama",      socrates_role="main"),
    "parmenides": dict(title="Parmenides", mode="frame_only", socrates_role="minor", narrator="Cephalus"),
    "timaeus":    dict(title="Timaeus",    mode="drama",      socrates_role="minor"),
    "critias":    dict(title="Critias",    mode="drama",      socrates_role="minor"),
    "sophist":    dict(title="Sophist",    mode="drama",      socrates_role="minor"),
    "statesman":  dict(title="Statesman",  mode="drama",      socrates_role="minor"),
    "laws":       dict(title="Laws",       mode="drama",      socrates_role="absent"),
}

# Project Gutenberg ids for Xenophon's Socratic works (tr. H. G. Dakyns).
# The script checks that the downloaded header names the expected title and
# skips the book with a warning if it does not.
XENOPHON_WORKS = {
    "xen_memorabilia": dict(gid=1177, title="Memorabilia", expect="Memorabilia"),
    "xen_apology":     dict(gid=1171, title="Apology",     expect="Apology"),
    "xen_symposium":   dict(gid=1181, title="Symposium",   expect="Symposium"),
    "xen_oeconomicus": dict(gid=1173, title="Economist",   expect="Econom"),
}
GUTENBERG_URLS = [
    "https://www.gutenberg.org/cache/epub/{gid}/pg{gid}.txt",
    "https://www.gutenberg.org/files/{gid}/{gid}-0.txt",
    "https://www.gutenberg.org/files/{gid}/{gid}.txt",
]

SYSTEM_PROMPT = (
    "You are Socrates of Athens. You do not hand out answers. You ask short, "
    "searching questions that help the other person examine what they "
    "believe, admit what you yourself do not know, and follow the argument "
    "wherever it leads."
)

# Passages touching on these themes are flagged so the safety layer can
# treat them with care (e.g. Phaedo discusses death and taking one's life).
SENSITIVE_PATTERNS = {
    "suicide": r"\b(suicide|take (his|her|their|one's|my|your) own life|kill (him|her|my|your|them)sel(f|ves)|lay violent hands)\b",
    "death": r"\b(death|dying|die|dies|died|corpse|hemlock|poison(ed)?|executed?|execution)\b",
    "violence": r"\b(murder(ed|er)?|slay|slain|beat(en)?|scourged?|tortur(e|ed))\b",
    # "desire" and "passion" are deliberately left out: in the Republic they
    # are terms of moral psychology, and matching them floods this flag.
    "sexuality": r"\b(lovers?|beloved|sexual|intercourse|embraces?)\b",
}

# Works held out of the SFT training split (meta.split == "eval"). Splitting
# by work avoids leakage: neighbouring examples share most of their context.
EVAL_WORKS = ("charmides", "crito", "euthyphro", "ion", "laches")

# Persona list entries that are not a named speaker ("And others who are
# mute auditors", "An Athenian Stranger", "The younger Socrates", ...).
NOT_A_NAME = {"A", "An", "And", "The", "Their", "Others", "Some"}


AGREEMENT: dict[str, float] = {}
PARTNER_AGREEMENT: dict[str, float] = {}

XHTML = "{http://www.w3.org/1999/xhtml}"
EPUB_TYPE = "{http://www.idpf.org/2007/ops}type"

# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------


@dataclass
class Turn:
    work_id: str
    work: str
    author: str
    translator: str
    source_url: str
    section: str          # e.g. "Book I" for the Republic, "" otherwise
    idx: int              # running index within the work
    speaker: str
    kind: str             # speech | narration
    attribution: str      # explicit | tagged | inferred | narration
    text: str
    words: int = field(init=False)

    def __post_init__(self):
        self.words = len(self.text.split())


# --------------------------------------------------------------------------
# Download (cached)
# --------------------------------------------------------------------------


def fetch(url: str, dest: Path, retries: int = 3) -> bytes:
    if dest.exists() and dest.stat().st_size > 0:
        return dest.read_bytes()
    dest.parent.mkdir(parents=True, exist_ok=True)
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "philocafe-corpus/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            dest.write_bytes(data)
            return data
        except Exception as e:  # noqa: BLE001 - report and retry
            last = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"download failed: {url}: {last}")


# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------


def norm(s: str) -> str:
    s = s.replace("⁠", "")          # word joiner used before em dashes
    s = s.replace(" ", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def el_text(el: ET.Element) -> str:
    """Text of an element without footnote markers or backlinks."""
    parts: list[str] = []

    def walk(e: ET.Element):
        et = e.get(EPUB_TYPE, "")
        if "noteref" in et or "backlink" in et:
            if e.tail:
                parts.append(e.tail)
            return
        if e.tag == XHTML + "br":
            parts.append(" ")
        if e.text:
            parts.append(e.text)
        for c in e:
            walk(c)
        if e.tail:
            parts.append(e.tail)

    if el.text:
        parts.append(el.text)
    for c in el:
        walk(c)
    return norm("".join(parts))


def leading_label(p: ET.Element) -> tuple[str | None, ET.Element | None]:
    """Return speaker name if <p> starts with <i>Name:</i>."""
    if (p.text or "").strip():
        return None, None
    kids = list(p)
    if not kids or kids[0].tag != XHTML + "i":
        return None, None
    label = norm("".join(kids[0].itertext()))
    m = re.fullmatch(r"([A-Z][A-Za-z .’']{1,40}):", label)
    return (m.group(1).strip(), kids[0]) if m else (None, None)


def text_after_label(p: ET.Element, label_el: ET.Element) -> str:
    saved = (label_el.text, list(label_el))
    label_el.text = ""
    for c in list(label_el):
        label_el.remove(c)
    t = el_text(p)
    label_el.text = saved[0]
    for c in saved[1]:
        label_el.append(c)
    return t


# --------------------------------------------------------------------------
# Plato (Standard Ebooks XHTML)
# --------------------------------------------------------------------------

# One verb list for detecting and for stripping attribution tags, so that
# every tag that decides a speaker is also removed from the training text.
TAG_VERBS = ("said|replied|answered|asked|rejoined|continued|added|proceeded|retorted"
             "|resumed|observed|interposed|exclaimed|interrupted")
SOC_TAG = re.compile(rf"\b(I ({TAG_VERBS})|({TAG_VERBS}) I)\b")
OTHER_TAG = re.compile(
    rf"\b((he|she|they) ({TAG_VERBS})"
    rf"|({TAG_VERBS}) (he|she)"
    rf"|({TAG_VERBS}) (?P<n1>[A-Z][a-z]+)"
    # "Adeimantus, his brother, interposed"
    rf"|(?P<n2>[A-Z][a-z]+)(?:, (?:his|her|the|a|an|who) [^,.;:?!]{{1,40}},)? ({TAG_VERBS}))\b")
# "..., Cephalus," / "Socrates, ..." / "my dear Glaucon, ...": a name used in
# direct address.
VOCATIVE = re.compile(r"(?:^|[,;:—!?]\s*|\bO |\b(?:dear|good|excellent|noble|sweet) )"
                      r"([A-Z][a-z]+)(?=[,;:?!—]|\.(?:\s|$))")
# Attribution clauses removed from the training text of narrated turns.
TAG_STRIP = re.compile(
    rf"(,\s*|\s+)(I|he|she|they) ({TAG_VERBS})(\s+to (me|him|her))?(?=[,;:.?!—])"
    rf"|(,\s*|\s+)({TAG_VERBS}) (I|he|she|[A-Z][a-z]+)(?=[,;:.?!—])")


# A persona named in narration; possessives ("Thrasymachus' retirement") are
# not the subject of the next tag.
NAME_MENTION = re.compile(r"\b([A-Z][a-z]+)\b(?![’'])")
# "So he said to me: Socrates, do you ..." : narration up to a colon tag.
COLON_TAG = re.compile(rf"\b(I|he|she|they|[A-Z][a-z]+) ({TAG_VERBS})( to (me|him|her|us))?:\s*")


LEAD_TAG = re.compile(
    rf"^(I|[A-Z][a-z]+) ({TAG_VERBS})( to (me|him|her))?:\s*")


def strip_tags(text: str) -> str:
    m = COLON_TAG.search(text)
    if m and m.end() < len(text):
        text = text[m.end():]                 # drop the narration before the speech
    t = LEAD_TAG.sub("", text)
    t = TAG_STRIP.sub("", t)
    t = re.sub(r"\s+([,;:.?!])", r"\1", t)
    t = re.sub(r",([.?!;:])", r"\1", t)
    t = re.sub(r"([?!])[.,:;]", r"\1", t)
    return norm(t[:1].upper() + t[1:])


def iter_blocks(section: ET.Element, heading: str = ""):
    """Yield (kind, payload, heading) in document order.

    kind: 'label' -> (speaker, text) | 'para' -> text | 'cont' -> text
    'cont' is verse/blockquote content that always continues the current turn.
    """
    for el in section:
        tag = el.tag.replace(XHTML, "")
        et = el.get(EPUB_TYPE, "")
        if "dramatis-personae" in et or "stage-direction" in et:
            continue
        if tag in ("h2", "h3", "h4", "h5", "header", "hgroup"):
            if tag != "h3":            # h3 is the work title itself
                heading = el_text(el)
            continue
        if tag == "section":
            yield from iter_blocks(el, heading)
            continue
        if tag == "table":
            for tr in el.iter(XHTML + "tr"):
                tds = tr.findall(XHTML + "td")
                if len(tds) >= 2 and "persona" in tds[0].get(EPUB_TYPE, ""):
                    yield "label", (el_text(tds[0]), el_text(tds[1])), heading
                elif tds:
                    yield "cont", " ".join(el_text(td) for td in tds), heading
            continue
        if tag == "blockquote":
            yield "cont", el_text(el), heading
            continue
        if tag == "p":
            who, lab = leading_label(el)
            if who:
                yield "label", (who, text_after_label(el, lab)), heading
            else:
                yield "para", el_text(el), heading
            continue
        if tag in ("div", "article"):
            yield from iter_blocks(el, heading)


def parse_plato(work_id: str, meta: dict, xhtml: bytes) -> list[Turn]:
    root = ET.fromstring(xhtml)
    text_sec = None
    for sec in root.iter(XHTML + "section"):
        if sec.get("id") == f"{work_id}-text":
            text_sec = sec
            break
    if text_sec is None:
        raise ValueError(f"{work_id}: no '{work_id}-text' section found")

    personae = set()
    for sec in text_sec.iter(XHTML + "section"):
        if "dramatis-personae" in sec.get(EPUB_TYPE, ""):
            for li in sec.iter(XHTML + "li"):
                personae |= persona_names(el_text(li))
    mode = meta["mode"]
    narrator = meta.get("narrator", "Socrates")
    base = dict(work_id=work_id, work=meta["title"], author="Plato",
                translator="Benjamin Jowett", source_url=SE_READ_BASE + f"{work_id}.xhtml")
    turns: list[Turn] = []
    last_partner = "Interlocutor"
    agree = [0, 0]
    partner_agree = [0, 0]
    exchange = None             # active entry of meta["exchanges"] (monologue mode)

    def add(speaker, kind, attribution, text, heading):
        if not text:
            return
        if heading.startswith(meta["title"]):
            heading = ""                      # the subtitle ("Lysis Or, Friendship") is not a section
        turns.append(Turn(**base, section=heading, idx=len(turns), speaker=speaker,
                          kind=kind, attribution=attribution, text=text))

    for kind, payload, heading in iter_blocks(text_sec):
        if kind == "label":
            speaker, text = payload
            add(speaker, "speech", "explicit", text, heading)
            if speaker != "Socrates":
                last_partner = speaker
            continue
        text = payload
        if not text:
            continue
        if kind == "cont" or mode in ("drama",):
            if turns:
                turns[-1].text = norm(turns[-1].text + " " + text)
                turns[-1].words = len(turns[-1].text.split())
            else:
                add("Narrator", "narration", "narration", text, heading)
            continue
        if mode == "monologue":
            if exchange and re.match(exchange["end"], text):
                exchange = None
            elif not exchange:
                exchange = next((x for x in meta.get("exchanges", ())
                                 if re.match(x["start"], text)), None)
            if exchange:
                # Socrates cross-examines someone: a short paragraph right
                # after his is the other person's reply. Speakers are not
                # labelled in the source, so the whole stretch is "inferred".
                prev = turns[-1] if turns else None
                answers = (prev is not None and prev.speaker == "Socrates"
                           and len(text.split()) <= 30 and not text.rstrip().endswith("?"))
                add(exchange["partner"] if answers else "Socrates", "speech", "inferred", text, heading)
            else:
                add("Socrates", "speech", "explicit", text, heading)
            continue
        if mode == "frame_only":
            add(narrator, "narration", "narration", text, heading)
            continue
        # mode == "narrated": Socrates tells the story in the first person.
        s = SOC_TAG.search(text)
        o = None
        for m in OTHER_TAG.finditer(text):
            name = m.group("n1") or m.group("n2")
            if name is None or name in personae:   # skip "Well said", "Then said"
                o = m
                break
        vocative = VOCATIVE.findall(text)
        if s and (not o or s.start() <= o.start()):
            speaker, attr = "Socrates", "tagged"
        elif o:
            name = o.group("n1") or o.group("n2")
            if name and name != "Socrates":
                # how often the tracked partner was already right when a tag
                # names the speaker; a rough check on the partner names given
                # to "he said" turns
                partner_agree[0] += name == last_partner
                partner_agree[1] += 1
                last_partner = name
            elif not name:
                # "he said": prefer a speaker the narration names just before
                # the tag ("For Glaucon ... was dissatisfied ... So he said")
                named = [n for n in NAME_MENTION.findall(text[:o.start()])
                         if n in personae and n != "Socrates" and n not in vocative]
                if named:
                    last_partner = named[-1]
            speaker, attr = last_partner, "tagged"
        elif "Socrates" in vocative:
            speaker, attr = last_partner, "inferred"     # someone addresses Socrates
        else:
            # No tag. Long paragraphs are not assumed to be Socrates': many
            # are the other speaker's speeches (Glaucon's ring of Gyges), so
            # fall back to alternation and leave the turn "inferred".
            prev = turns[-1].speaker if turns else "Socrates"
            if any(v in personae and v != "Socrates" for v in vocative):
                speaker, attr = "Socrates", "inferred"   # Socrates addresses someone
            else:
                speaker = last_partner if prev == "Socrates" else "Socrates"
                attr = "inferred"
        if attr == "tagged" and turns and turns[-1].kind == "speech":
            # agreement between explicit tags and simple alternation is a
            # rough estimate of how reliable the inferred turns are
            alt = "Socrates" if turns[-1].speaker != "Socrates" else "other"
            got = "Socrates" if speaker == "Socrates" else "other"
            agree[0] += alt == got
            agree[1] += 1
        if speaker == "Socrates":
            addressed = [v for v in vocative if v in personae and v != "Socrates"]
            if addressed:
                last_partner = addressed[0]
        clean = strip_tags(text) if attr == "tagged" else text
        add(speaker, "speech", attr, clean, heading)
    if agree[1]:
        AGREEMENT[work_id] = round(agree[0] / agree[1], 3)
    if partner_agree[1]:
        PARTNER_AGREEMENT[work_id] = round(partner_agree[0] / partner_agree[1], 3)
    return turns


def persona_names(entry: str) -> set[str]:
    """Speaker names in one dramatis personae entry.

    "Socrates, who is the narrator" -> {"Socrates"}; "Nicias, Laches, Socrates"
    -> all three; "Cleinias (a Cretan)" -> {"Cleinias"}; "And others who are
    mute auditors." and "An Athenian Stranger" -> nothing.
    """
    names = set()
    for part in re.sub(r"\([^)]*\)", "", entry).split(","):
        part = part.strip().rstrip(".")
        if re.fullmatch(r"[A-Z][a-z]+", part) and part not in NOT_A_NAME:
            names.add(part)
    return names


# --------------------------------------------------------------------------
# Xenophon (Project Gutenberg plain text)
# --------------------------------------------------------------------------

PG_START = re.compile(r"^\*\*\* ?START OF (THE|THIS) PROJECT GUTENBERG EBOOK.*$", re.M | re.I)
PG_END = re.compile(r"^\*\*\* ?END OF (THE|THIS) PROJECT GUTENBERG EBOOK.*$", re.M | re.I)


def clean_gutenberg(raw: str) -> list[str]:
    """Strip PG header/footer, front matter, footnotes; return paragraphs."""
    raw = raw.replace("\r\n", "\n").lstrip("﻿")
    m1, m2 = PG_START.search(raw), PG_END.search(raw)
    body = raw[m1.end(): m2.start()] if m1 and m2 else raw
    # Footnote blocks such as "[Footnote 1: ...]" (may span lines).
    body = re.sub(r"\[Footnote[^\]]*\]", "", body, flags=re.S)
    paras = [p for p in re.split(r"\n\s*\n", body)]
    out: list[str] = []
    started = False
    for p in paras:
        lines = [l.strip() for l in p.split("\n")]
        text = " ".join(l for l in lines if l)
        if not text:
            continue
        if re.match(r"^(BOOK|CHAPTER|PART)\s+[IVXLC0-9]+\b", text) or re.match(r"^[IVXLC]+\.?$", text):
            started = True
            out.append("§" + text)            # marks a heading
            continue
        if not started:
            continue                          # title page, contents, preface
        if re.match(r"^\(\d+\)\s", text):     # Dakyns-style footnote paragraph
            continue
        if re.match(r"^(Transcriber|Produced by|End of)", text, re.I):
            continue
        text = re.sub(r"\s*\(\d+\)", "", text)       # inline "(1)" markers
        text = re.sub(r"\s*\[\d+\]", "", text)       # inline "[1]" markers
        text = re.sub(r"_([^_]+)_", r"\1", text)     # _italics_
        out.append(norm(text))
    if not started:                            # no headings found: keep everything
        return [norm(" ".join(p.split())) for p in paras if p.strip()]
    return out


def parse_xenophon(work_id: str, meta: dict, raw: str, url: str) -> list[Turn]:
    m = PG_START.search(raw)
    head = raw[: m.start()] if m else raw[:1500]   # PG header: title, author, translator
    if "Xenophon" not in head or meta["expect"].lower() not in head.lower():
        raise ValueError(f"{work_id}: Gutenberg #{meta['gid']} does not look like "
                         f"Xenophon's {meta['title']}; check the id")
    turns: list[Turn] = []
    heading = ""
    for p in clean_gutenberg(raw):
        if p.startswith("§"):
            heading = p[1:]
            continue
        turns.append(Turn(work_id=work_id, work=meta["title"], author="Xenophon",
                          translator="H. G. Dakyns", source_url=url, section=heading,
                          idx=len(turns), speaker="Xenophon", kind="narration",
                          attribution="narration", text=p))
    return turns


# --------------------------------------------------------------------------
# Outputs
# --------------------------------------------------------------------------


def build_sft(turns: list[Turn], include_inferred: bool, context: int,
              min_words: int, max_words: int = 200,
              eval_works: tuple[str, ...] = EVAL_WORKS) -> list[dict]:
    """One example per Socrates turn; previous turns become the conversation.

    Targets longer than `max_words` (set speeches, not conversation) and
    targets that still read as narration ("I replied that ...") are skipped.
    """
    ok = {"explicit", "tagged"} | ({"inferred"} if include_inferred else set())
    examples = []
    by_work: dict[str, list[Turn]] = {}
    for t in turns:
        by_work.setdefault(t.work_id, []).append(t)
    for work_turns in by_work.values():
        for i, t in enumerate(work_turns):
            if t.speaker != "Socrates" or t.kind != "speech" or t.attribution not in ok:
                continue
            if t.words < min_words or t.words > max_words or i == 0:
                continue
            if t.attribution != "explicit" and is_narration(t.text):
                continue                      # only narrated works carry these
            hist = []
            for h in work_turns[max(0, i - context): i]:
                if h.kind != "speech" or h.attribution not in ok:
                    hist = []                 # don't stitch across narration
                    continue
                role = "assistant" if h.speaker == "Socrates" else "user"
                content = h.text if role == "assistant" else f"{h.speaker}: {h.text}"
                if hist and hist[-1]["role"] == role:
                    hist[-1]["content"] += "\n\n" + content
                else:
                    hist.append({"role": role, "content": content})
            while hist and hist[0]["role"] != "user":
                hist.pop(0)
            if not hist or hist[-1]["role"] != "user":
                continue
            examples.append({
                "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *hist,
                             {"role": "assistant", "content": t.text}],
                "meta": {"work": t.work, "work_id": t.work_id, "section": t.section,
                         "turn_idx": t.idx, "attribution": t.attribution,
                         "is_question": t.text.rstrip().endswith("?"),
                         "split": "eval" if t.work_id in eval_works else "train",
                         "source_url": t.source_url},
            })
    return examples


# First-person narration left in a Socrates turn: reported speech ("I asked
# him whether", "I replied that") or scene-setting ("Upon entering we found").
NARRATION = re.compile(
    rf"\bI ({TAG_VERBS}) (that|whether|him|her|them|if)\b"
    r"|\b(I|we) (went|came|found|saw|entered|sat down|turned|perceived|noticed)\b"
    r"|^(Upon|On|When|After|Then|So) (entering|arriving|coming|we|I)\b")


def is_narration(text: str) -> bool:
    return bool(NARRATION.search(text) or SOC_TAG.search(text))


def flag_sensitive(text: str) -> list[str]:
    return [k for k, pat in SENSITIVE_PATTERNS.items() if re.search(pat, text, re.I)]


def split_words(text: str, limit: int) -> list[str]:
    """Split text into pieces of at most `limit` words, at sentence ends
    where possible (a single longer sentence is cut between words)."""
    words = text.split()
    if len(words) <= limit:
        return [text]
    pieces: list[str] = []
    cur: list[str] = []
    for sent in re.split(r"(?<=[.?!])\s+", text):
        w = sent.split()
        if cur and len(cur) + len(w) > limit:
            pieces.append(" ".join(cur))
            cur = []
        while len(w) > limit:
            pieces.append(" ".join(w[:limit]))
            w = w[limit:]
        cur += w
    if cur:
        pieces.append(" ".join(cur))
    return pieces


def speaker_label(t: Turn) -> str:
    """Line prefix in a passage. Inferred speakers are not named, so that a
    guessed attribution is never presented to the persona as fact."""
    if t.kind == "narration":
        return ""
    if t.attribution == "inferred":
        return "[speaker uncertain] "
    return f"{t.speaker}: "


def build_passages(turns: list[Turn], target_words: int) -> list[dict]:
    """Group turns into passages of at most `target_words` words.

    Turns longer than that are split at sentence ends, so every passage fits
    the embedding model's input (all-MiniLM-L6-v2 reads ~256 tokens).
    """
    passages = []
    buf: list[tuple[Turn, int, str]] = []      # (turn, piece number, text)
    size = 0                                   # words in buf, speaker labels included
    used: set[str] = set()

    def flush():
        if not buf:
            return
        lines: list[str] = []
        for j, (t, part, piece) in enumerate(buf):
            if j and buf[j - 1][0] is t:
                lines[-1] += " " + piece
            else:
                lines.append(speaker_label(t) + piece)
        text = "\n".join(lines)
        f = buf[0][0]
        # Content-based id: stays the same when the corpus is rebuilt and turn
        # numbers shift; changes only when the passage text changes.
        pid, n = None, 0
        while pid is None or pid in used:     # identical text twice in a work: rehash
            salt = f"\0{n}" if n else ""
            pid = f"{f.work_id}-{hashlib.sha256((text + salt).encode('utf-8')).hexdigest()[:8]}"
            n += 1
        used.add(pid)
        known = [(t, piece) for t, _, piece in buf
                 if t.kind == "speech" and t.attribution != "inferred"]
        passages.append({
            "id": pid,
            "author": f.author, "work": f.work, "translator": f.translator,
            "section": f.section, "turn_range": [f.idx, buf[-1][0].idx],
            # only speakers whose attribution is explicit or tagged
            "speakers": sorted({t.speaker for t, _ in known} |
                               {t.speaker for t, _, _ in buf if t.kind == "narration"}),
            "socrates_words": sum(len(piece.split()) for t, piece in known if t.speaker == "Socrates"),
            "speaker_uncertain": any(t.attribution == "inferred" for t, _, _ in buf),
            "sensitive": flag_sensitive(text),
            "source_url": f.source_url,
            "text": text,
        })
        buf.clear()

    for t in turns:
        if buf and (t.work_id != buf[0][0].work_id or t.section != buf[0][0].section):
            flush()
            size = 0
        label = len(speaker_label(t).split())
        for part, piece in enumerate(split_words(t.text, target_words - label)):
            n = len(piece.split()) + label
            if buf and size + n > target_words:
                flush()
                size = 0
            buf.append((t, part, piece))
            size += n
    flush()
    return passages


def write_jsonl(path: Path, rows) -> int:
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("data/processed/socrates"))
    ap.add_argument("--raw", type=Path, default=Path("data/raw/socrates"),
                    help="download cache (git-ignored)")
    ap.add_argument("--works", nargs="*", help="Plato work ids to include (default: all with Socrates)")
    ap.add_argument("--main-only", action="store_true",
                    help="only works where Socrates leads (default: also those where he is minor)")
    ap.add_argument("--with-xenophon", action="store_true", help="also fetch Xenophon from Gutenberg")
    ap.add_argument("--include-inferred", action="store_true",
                    help="use speaker-inferred turns from narrated dialogues in SFT")
    ap.add_argument("--context-turns", type=int, default=6)
    ap.add_argument("--min-words", type=int, default=3, help="min words for a Socrates SFT target")
    ap.add_argument("--max-words", type=int, default=200, help="max words for a Socrates SFT target")
    ap.add_argument("--eval-works", default=",".join(EVAL_WORKS),
                    help="comma-separated work ids whose SFT examples get split=eval")
    ap.add_argument("--passage-words", type=int, default=180,
                    help="max words per RAG passage (the embedding model reads ~256 tokens)")
    args = ap.parse_args(argv)

    out: Path = args.out
    raw_dir: Path = args.raw
    out.mkdir(parents=True, exist_ok=True)

    turns: list[Turn] = []
    report = {}
    for wid, meta in PLATO_WORKS.items():
        if args.works and wid not in args.works:
            continue
        if not args.works:
            if meta["socrates_role"] == "absent":
                continue
            if args.main_only and meta["socrates_role"] != "main":
                continue
        try:
            data = fetch(SE_BASE + f"{wid}.xhtml", raw_dir / "plato" / f"{wid}.xhtml")
            wt = parse_plato(wid, meta, data)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {wid}: {e}", file=sys.stderr)
            continue
        turns.extend(wt)
        report[wid] = summarize(wt)
        if wid in AGREEMENT:
            report[wid]["tag_vs_alternation_agreement"] = AGREEMENT[wid]
        if wid in PARTNER_AGREEMENT:
            report[wid]["partner_name_agreement"] = PARTNER_AGREEMENT[wid]

    if args.with_xenophon:
        for wid, meta in XENOPHON_WORKS.items():
            data, url = None, None
            for tmpl in GUTENBERG_URLS:
                url = tmpl.format(gid=meta["gid"])
                try:
                    data = fetch(url, raw_dir / "xenophon" / f"pg{meta['gid']}.txt")
                    break
                except Exception as e:  # noqa: BLE001
                    print(f"[warn] {wid}: {e}", file=sys.stderr)
            if data is None:
                continue
            try:
                wt = parse_xenophon(wid, meta, data.decode("utf-8", "replace"), url)
            except Exception as e:  # noqa: BLE001
                print(f"[warn] {e}", file=sys.stderr)
                continue
            turns.extend(wt)
            report[wid] = summarize(wt)

    n_turns = write_jsonl(out / "turns.jsonl", (asdict(t) for t in turns))
    eval_works = tuple(w for w in args.eval_works.split(",") if w)
    sft = build_sft(turns, args.include_inferred, args.context_turns, args.min_words,
                    args.max_words, eval_works)
    n_sft = write_jsonl(out / "socrates_sft.jsonl", sft)
    n_pass = write_jsonl(out / "rag_passages.jsonl", build_passages(turns, args.passage_words))
    (out / "stats.json").write_text(json.dumps(
        {"source": {"standard_ebooks_repo": SE_REPO, "standard_ebooks_commit": SE_COMMIT},
         "turns": n_turns, "sft_examples": n_sft,
         "sft_split": {k: sum(e["meta"]["split"] == k for e in sft) for k in ("train", "eval")},
         "passages": n_pass, "works": report},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"turns={n_turns} sft={n_sft} passages={n_pass} -> {out}")
    return 0


def summarize(wt: list[Turn]) -> dict:
    soc = [t for t in wt if t.speaker == "Socrates"]
    attrs: dict[str, int] = {}
    for t in wt:
        attrs[t.attribution] = attrs.get(t.attribution, 0) + 1
    return {"turns": len(wt), "socrates_turns": len(soc),
            "socrates_words": sum(t.words for t in soc),
            "total_words": sum(t.words for t in wt), "attribution": attrs}


if __name__ == "__main__":
    sys.exit(main())
