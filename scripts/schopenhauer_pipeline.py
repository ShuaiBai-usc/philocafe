#!/usr/bin/env python3
"""Philocafe · Schopenhauer corpus pipeline.

Downloads public-domain English translations of Schopenhauer, strips
everything that is not Schopenhauer's text (Project Gutenberg headers and
licence, translators' prefaces and notes, footnotes and footnote markers,
illustrations, the translators' abstract and index), splits the works into
paragraphs, and writes the same files as the Socrates and Seneca pipelines
(docs/socrates.md, docs/seneca.md), so build_sqlite.py and retrieval.py work
as is:

  turns.jsonl                one record per paragraph ("turn"), all works
  schopenhauer_sft.jsonl     chat-format examples, Schopenhauer as the assistant
  rag_passages.jsonl         passages of at most ~180 words with citations
  caution_candidates.csv     flagged passages for the persona config's caution list

Sources (plain-text Project Gutenberg transcriptions mirrored on GitHub by
GITenberg, pinned commits; Standard Ebooks has no Schopenhauer release yet):
  * The World as Will and Idea, 3 vols, tr. R. B. Haldane and J. Kemp (1883-1886)
  * Seven volumes of essays from Parerga and Paralipomena, tr. T. Bailey
    Saunders (1889-1896)

Most of Schopenhauer is prose, so a "turn" is one paragraph in his voice. Two
essays are real dialogues (Religion: Demopheles and Philalethes; Immortality:
Thrasymachos and Philalethes); Philalethes is Schopenhauer's spokesman, and
those exchanges are the main SFT source. See docs/schopenhauer.md.

Only the Python standard library is used. Run from the repository root:

    python3 scripts/schopenhauer_pipeline.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path

# --------------------------------------------------------------------------
# Source configuration
# --------------------------------------------------------------------------

# Pinned to commits so that upstream changes cannot silently change the
# output. `file` is parsed; `link` is the file shown to users as the citation
# (the 7-bit ASCII edition of the essays, because jsDelivr serves .txt as
# UTF-8 and the Latin-1 files would show broken accents).
SOURCES = {
    "wwi1": dict(repo="GITenberg/The-World-As-Will-And-Idea--Vol.-1-of-3-_38427",
                 commit="153d1323fa5943b6da2233d10e91c06a586e409f",
                 file="38427-0.txt", link="38427-0.txt", encoding="utf-8",
                 translator="R. B. Haldane and J. Kemp"),
    "wwi2": dict(repo="GITenberg/The-World-As-Will-And-Idea--Vol.-2-of-3-_40097",
                 commit="ea47b6cf0437bd2ec8b53308da9300c1386373f0",
                 file="40097-0.txt", link="40097-0.txt", encoding="utf-8",
                 translator="R. B. Haldane and J. Kemp"),
    "wwi3": dict(repo="GITenberg/The-World-As-Will-And-Idea--Vol.-3-of-3-_40868",
                 commit="f17690ffb0c4d0d633bbc0e510d0d530dcb4287b",
                 file="40868-0.txt", link="40868-0.txt", encoding="utf-8",
                 translator="R. B. Haldane and J. Kemp"),
    "wisdom_of_life": dict(repo="GITenberg/The-Essays-of-Arthur-Schopenhauer--the-Wisdom-of-Life_10741",
                           commit="0d0f490624db4f8265f3d4f23bc5fb02e88ada81",
                           file="10741-8.txt", link="10741.txt", encoding="latin-1",
                           translator="T. Bailey Saunders"),
    "counsels": dict(repo="GITenberg/The-Essays-of-Arthur-Schopenhauer--Counsels-and-Maxims_10715",
                     commit="1302cc710181db7111873dd0487d3a5a30287077",
                     file="10715-8.txt", link="10715.txt", encoding="latin-1",
                     translator="T. Bailey Saunders"),
    "pessimism": dict(repo="GITenberg/The-Essays-of-Arthur-Schopenhauer--Studies-in-Pessimism_10732",
                      commit="73e5702baefa1f0c0c9294fdbe21da25b6920d15",
                      file="10732-8.txt", link="10732.txt", encoding="latin-1",
                      translator="T. Bailey Saunders"),
    "controversy": dict(repo="GITenberg/The-Essays-of-Arthur-Schopenhauer--the-Art-of-Controversy_10731",
                        commit="4462063888e5e5c0f3bbd6bfdefe40b571d6124d",
                        file="10731-8.txt", link="10731.txt", encoding="latin-1",
                        translator="T. Bailey Saunders"),
    "literature": dict(repo="GITenberg/The-Essays-of-Arthur-Schopenhauer--The-Art-of-Literature_10714",
                       commit="8e2bb98ba91164391af3c03953e3bd60e328c9d7",
                       file="10714-8.txt", link="10714.txt", encoding="latin-1",
                       translator="T. Bailey Saunders"),
    "human_nature": dict(repo="GITenberg/The-Essays-of-Arthur-Schopenhauer--On-Human-Nature_10739",
                         commit="bff647e8f9134fad10e907f34b9088fed3d57bcf",
                         file="10739-8.txt", link="10739.txt", encoding="latin-1",
                         translator="T. Bailey Saunders"),
    "religion": dict(repo="GITenberg/The-Essays-of-Arthur-Schopenhauer--Religion-a-Dialogue-Etc._10833",
                     commit="c9b1195f4799e92e966d22fa3c60f58bc9700518",
                     file="10833-8.txt", link="10833.txt", encoding="latin-1",
                     translator="T. Bailey Saunders"),
}


def raw_url(key: str) -> str:
    s = SOURCES[key]
    return f"https://raw.githubusercontent.com/{s['repo']}/{s['commit']}/{s['file']}"


def read_url(key: str) -> str:
    # Citation link shown to users: the same pinned commit served by jsDelivr.
    s = SOURCES[key]
    return f"https://cdn.jsdelivr.net/gh/{s['repo']}@{s['commit']}/{s['link']}"


# The World as Will and Idea: one work, three volumes. Work ids have no
# hyphen, so chunk_id "schopenhauer-<work>-<8hex>" splits cleanly.
WWI = {
    "wwi1": dict(volume="I", start="PREFACE TO THE FIRST EDITION.", end="FOOTNOTES"),
    "wwi2": dict(volume="II", start="APPENDIX: CRITICISM OF THE KANTIAN PHILOSOPHY.", end="FOOTNOTES"),
    # Vol. III ends with the translators' abstract of the Fourfold Root
    # ("APPENDIX.") and the index, neither of which is Schopenhauer's text.
    "wwi3": dict(volume="III", start="SUPPLEMENTS TO THE SECOND BOOK.", end="APPENDIX."),
}
WWI_TITLE = "The World as Will and Idea"

# Saunders' essay volumes. `start` is the block where Schopenhauer's text
# begins (after the translator's preface, signed "T.B.S."); `inclusive` says
# whether that block is itself a heading to keep. `tops` are the headings of
# the separate essays (exact text, footnote markers removed); other all-caps
# headings become sub-sections, except those in `ignore`.
ESSAYS = {
    "wisdom_of_life": dict(
        title="The Wisdom of Life", start="INTRODUCTION.", inclusive=True,
        tops=["INTRODUCTION."], ignore=["THE WISDOM OF LIFE."]),
    "counsels": dict(
        title="Counsels and Maxims", start="INTRODUCTION.", inclusive=True,
        tops=["INTRODUCTION."], ignore=[]),
    "pessimism": dict(
        title="Studies in Pessimism", start="T.B.S.", inclusive=False,
        tops=["ON THE SUFFERINGS OF THE WORLD.", "THE VANITY OF EXISTENCE.", "ON SUICIDE.",
              "IMMORTALITY: A DIALOGUE.", "PSYCHOLOGICAL OBSERVATIONS.", "ON EDUCATION.",
              "OF WOMEN.", "ON NOISE.", "A FEW PARABLES."],
        ignore=["THRASYMACHOS--PHILALETHES."]),
    "controversy": dict(
        title="The Art of Controversy", start="February, 1896", inclusive=False,
        tops=["THE ART OF CONTROVERSY.", "ON THE COMPARATIVE PLACE OF INTEREST AND BEAUTY IN WORKS OF ART.",
              "PSYCHOLOGICAL OBSERVATIONS.", "ON THE WISDOM OF LIFE: APHORISMS.", "GENIUS AND VIRTUE."],
        ignore=[]),
    "literature": dict(
        title="The Art of Literature", start="T.B.S.", inclusive=False,
        tops=["ON AUTHORSHIP.", "ON STYLE.", "ON THE STUDY OF LATIN.", "ON MEN OF LEARNING.",
              "ON THINKING FOR ONESELF.", "ON CRITICISM.", "ON REPUTATION.", "ON GENIUS."],
        ignore=[]),
    "human_nature": dict(
        title="On Human Nature", start="T.B.S.", inclusive=False,
        tops=["HUMAN NATURE.", "GOVERNMENT.", "FREE-WILL AND FATALISM.", "CHARACTER.",
              "MORAL INSTINCT.", "ETHICAL REFLECTIONS."],
        ignore=[]),
    "religion": dict(
        title="Religion: A Dialogue, Etc.", start="T.B. SAUNDERS.", inclusive=False,
        tops=["RELIGION.", "A FEW WORDS ON PANTHEISM.", "ON BOOKS AND READING.", "PHYSIOGNOMY.",
              "PSYCHOLOGICAL OBSERVATIONS.", "THE CHRISTIAN SYSTEM."],
        ignore=["A DIALOGUE."]),
}
# Section names that read better than a title-cased heading.
SECTION_NAMES = {"RELIGION.": "Religion: A Dialogue", "PHYSIOGNOMY.": "On Physiognomy"}

PERSONA = "Schopenhauer"
# Philalethes ("lover of truth") speaks for Schopenhauer in both dialogues.
PERSONA_VOICES = ("Schopenhauer", "Philalethes")
DIALOGUE_SPEAKERS = ("Philalethes", "Demopheles", "Thrasymachos")

SYSTEM_PROMPT = (
    "You are Arthur Schopenhauer, talking with someone who wants to think a "
    "question through. You reason from close observation of everyday life, "
    "say plainly what you think and why, and test claims against experience "
    "rather than authority. You may describe suffering honestly, but you "
    "never urge anyone towards despair or self-harm: your aim is clear "
    "seeing, compassion and calm."
)

# Passages touching on these themes are flagged so they can be reviewed and
# handled with care (team decision 2026-10-14: pessimistic material may stay,
# but the persona must not drive a user into a downward spiral). Flags are
# hints for corpus analysis and for the persona config's tier-2 caution list,
# not a filter; retrieval does not use them (design doc v0.2, section 7.1).
_POSS = r"(his|her|their|one's|one’s|my|your|our)"
SENSITIVE_PATTERNS = {
    "suicide": (
        r"\b(suicides?|suicidal|self-destruction|self-murder|felo de se"
        rf"|(take|took|taking|takes|end|ended|ending|ends|put an end to) {_POSS} (own )?life"
        r"|(kill|kills|killed|killing|slay|slew|slain|destroy|destroys|destroyed) (him|her|my|your|them|one|our)sel(f|ves)"
        r"|(lay|lays|laid|laying) (violent )?hands (up)?on (him|her|them|my|your|one|our)sel(f|ves)"
        rf"|(die|dies|died|perish|perished|fell) by {_POSS} own hands?"
        r"|voluntary death|starv(e|ed|es|ing) (him|her|them|your|my|one)sel(f|ves)|starv(e|ed|ing) to death"
        r"|(death|die) by starvation|(abstain|abstained|abstaining|refus(e|ed|ing)) (from )?(food|nourishment)"
        r"|(leave|leaves|left|leaving|quit|quits|quitting) life|(depart|departs|departed|departure) from life"
        r"|courage to die|desire to die|wish(es|ed)? to die|longing for death)\b"),
    # Statements that devalue life as such (antinatalism, "better not to
    # be"). Schopenhauer's doctrine of suffering is everywhere; this narrower
    # pattern marks the lines most likely to hurt a vulnerable reader.
    "despair": (
        r"\b(despair(ing|ed|s)?|hopeless(ness)?|better (not|never) to (have been born|be|exist|have existed)"
        r"|not to (be|have been) born|never (to )?have been born|would (rather|sooner) not (be|exist|have been)"
        r"|non-existence (is|would be) (preferable|better)|preferable to (existence|life)"
        r"|(life|existence) (is|was) (a|an) (mistake|misfortune|punishment|penal|business that does not cover)"
        r"|(worthless(ness)?|misery|wretchedness|vanity|nothingness|emptiness) of (life|human life|existence)"
        r"|(life|existence) (is|has) no (value|worth|meaning)|not worth living|weariness of life|tired of life"
        r"|taedium vitae|(world|life|existence) is (hell|a hell)|curse of existence|sufferings? of the world)\b"),
    "death": r"\b(death|dying|die|dies|died|corpse|poison(ed)?|executed?|execution|funeral)\b",
    "violence": r"\b(murder(ed|er|s)?|slay|slain|slaughter(ed)?|beat(en)?|scourg(e|ed|ing)|tortur(e|ed|es)|crucif\w*|cruelty)\b",
    "grief": r"\b(grief|griefs|griev(e|es|ed|ing)|mourn(s|ed|ing)?|bereave(d|ment))\b",
    "sexuality": r"\b(lovers?|sexual|sexes|intercourse|adulter(y|er|ers|ess)|lust|pederasty|procreation|generative)\b",
    # Schopenhauer's generalisations about women, Jews and "races" are
    # prejudice the persona must not repeat; the essay "Of Women" is flagged
    # whole (SECTION_FLAGS).
    "prejudice": (r"\b(Jews?|Jewish|Judaism|negro(es)?|savages?|the fair sex|the female sex"
                  r"|(women|woman) (are|is) (by nature|childish|inferior|the second sex|incapable))\b"),
}

# Keys below are "<work_id>|<section>". Every passage in these sections gets
# the listed flags, regardless of the regex.
SECTION_FLAGS = {
    "pessimism|On Suicide": ["suicide"],
    "wwi|Fourth Book: The World as Will, § 69": ["suicide"],     # the section on suicide
    "pessimism|Of Women": ["prejudice"],
}

# Sections that discuss suicide somewhere, read by hand, in addition to every
# section where the suicide pattern matches at least once. All passages in
# such sections get "suicide_context".
SUICIDE_CONTEXT_SECTIONS = (
    "pessimism|On the Sufferings of the World",   # "better not to be"; suicide as a way out
    "pessimism|The Vanity of Existence",
    "wwi|Supplements to the Fourth Book, Chapter XLVI: On the Vanity and Suffering of Life",
    "wwi|Supplements to the Fourth Book, Chapter XLVIII: On the Doctrine of the Denial of the Will to Live",
)

# SFT examples held out as an eval split: the whole Immortality dialogue,
# and objection examples from every tenth section of each work.
EVAL_SECTIONS = ("pessimism|Immortality: A Dialogue",)
EVAL_EVERY = 10

# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------


@dataclass
class Turn:
    # Same fields as the Socrates/Seneca Turn, plus `volume` and `sensitive`
    # (build_sqlite.py ignores keys it does not know).
    work_id: str
    work: str
    author: str
    translator: str
    source_url: str
    section: str          # "Fourth Book: The World as Will, § 69", "On Suicide"
    idx: int              # running paragraph index within the work
    speaker: str          # "Schopenhauer"; dialogue speakers in Religion / Immortality
    kind: str             # speech
    attribution: str      # explicit
    text: str
    volume: str = ""      # "I", "II", "III" for The World as Will and Idea
    sensitive: list = field(default_factory=list)
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
            with urllib.request.urlopen(req, timeout=120) as r:
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

SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "with",
               "from", "into", "its", "but", "nor"}


def title_case(s: str) -> str:
    """'ON THE VANITY AND SUFFERING OF LIFE.' -> 'On the Vanity and Suffering of Life'."""
    s = s.replace("_", "").strip().rstrip(".")
    words = re.split(r"(\s+|-)", s.lower())
    out, first = [], True
    for w in words:
        if not w.strip() or w == "-":
            out.append(w)
            continue
        core = w.strip("“”\"'(_")
        if not first and core in SMALL_WORDS:
            out.append(w)
        else:
            i = len(w) - len(w.lstrip("“”\"'(_"))
            out.append(w[:i] + w[i:i + 1].upper() + w[i + 1:])
        first = w.endswith(":")
    return "".join(out).replace("A Priori", "a Priori").replace("’S ", "’s ").replace("'S ", "'s ")


def norm(s: str) -> str:
    s = s.replace(" ", " ").replace("‐", "-")   # U+2010 hyphen used in the WWI files
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def clean_text(s: str) -> str:
    """Inline cleanup shared by all sources."""
    while re.search(r"\[Footnote", s):                # inline footnotes, possibly nested
        new = re.sub(r"\s?\[Footnote[^\[\]]*\]", "", s)
        new = re.sub(r"(\[Footnote[^\[\]]*)\[[^\[\]]*\]", r"\1", new)
        if new == s:
            break
        s = new
    s = re.sub(r"\[Greek:[^\]]*\]", "[Greek]", s)
    s = re.sub(r"\[Illustration[^\]]*\]", "", s)
    s = re.sub(r"\s?\[\d+\]", "", s)                 # essays: footnote markers [1]
    s = re.sub(r"(?<=[^\s(])\(\d+\)", "", s)        # WWI: footnote markers "word,(12)"
    s = s.replace("_", "")                           # italics
    s = s.replace("--", "—")
    s = re.sub(r"\s+([,;:.!?])", r"\1", s)
    return norm(s)


def blocks_of(raw: str) -> list[str]:
    """Blank-line separated blocks, without the Project Gutenberg header and licence."""
    text = raw.replace("\r", "")
    m = re.search(r"\*\*\* ?START OF[^\n]*(\n[^\n]+)?\*\*\*", text)
    if m:
        text = text[m.end():]
    end = re.search(r"\*\*\* ?END OF|End of (the )?Project Gutenberg", text)
    if end:
        text = text[:end.start()]
    return [b for b in re.split(r"\n[ \t]*\n", text) if b.strip()]


def is_caps_heading(block: str) -> bool:
    s = re.sub(r"\[\d+\]", "", block.strip())
    return bool(re.search(r"[A-Z]{2}", s)) and not re.search(r"[a-z]", s) and len(s) < 120


def is_indented(block: str) -> bool:
    lines = [ln for ln in block.split("\n") if ln.strip()]
    return all(re.match(r"[ \t]{2,}", ln) for ln in lines)


SEPARATOR = re.compile(r"^[\s*‐\-]+$")


# --------------------------------------------------------------------------
# Parsing: shared paragraph collector
# --------------------------------------------------------------------------


class Collector:
    """Builds turns from paragraphs; handles quotations and speaker labels."""

    def __init__(self, base: dict):
        self.base = base
        self.turns: list[Turn] = []
        self.label: str | None = None    # "_The Subject._" block before a speech

    def add(self, section: str, text: str, speaker: str = PERSONA):
        text = clean_text(text)
        if not text or not section:
            return
        if self.label:
            text, self.label = f"{self.label}: {text}", None
        self.turns.append(Turn(**self.base, section=section, idx=len(self.turns),
                               speaker=speaker, kind="speech", attribution="explicit", text=text))

    def join(self, section: str, text: str) -> bool:
        """Append a quotation to the previous paragraph of the same section.
        A quotation that opens a section (a motto) is dropped."""
        text = clean_text(text)
        if self.turns and self.turns[-1].section == section and text:
            t = self.turns[-1]
            t.text = norm(t.text + " " + text)
            t.words = len(t.text.split())
            return True
        return False


def paragraph(block: str):
    """(speaker, text) for a paragraph; dialogue paragraphs start "_Name_. "."""
    s = block.strip()
    m = re.match(rf"_({'|'.join(DIALOGUE_SPEAKERS)})_?\.(_)?\s*(.*)", s, re.S)
    if m:
        return m.group(1), m.group(3)
    return PERSONA, s


def skip_footnote(blocks: list[str], i: int) -> int:
    """Index after a "[Footnote ...]" that may span several blocks."""
    depth = 0
    while i < len(blocks):
        depth += blocks[i].count("[") - blocks[i].count("]")
        i += 1
        if depth <= 0:
            break
    return i


# --------------------------------------------------------------------------
# Parsing: essays (Saunders)
# --------------------------------------------------------------------------


def essay_turns(work_id: str, raw: str) -> list[Turn]:
    cfg = ESSAYS[work_id]
    src = SOURCES[work_id]
    blocks = blocks_of(raw)
    start = next(i for i, b in enumerate(blocks) if b.strip() == cfg["start"])
    if not cfg["inclusive"]:
        start += 1
    col = Collector(dict(work_id=work_id, work=cfg["title"], author=PERSONA,
                         translator=src["translator"], source_url=read_url(work_id)))
    essay = chapter = sub = ""
    pending_chapter = False

    def section():
        return ", ".join(p for p in (essay, chapter, sub) if p)

    i = start
    while i < len(blocks):
        b = blocks[i]
        s = b.strip()
        h = re.sub(r"\s?\[\d+\]", "", s)
        if s.startswith("[Footnote"):
            i = skip_footnote(blocks, i)
            continue
        i += 1
        if SEPARATOR.match(s):
            continue
        if h in cfg["ignore"]:
            continue
        if h in cfg["tops"]:
            essay, chapter, sub = SECTION_NAMES.get(h, title_case(h)), "", ""
            continue
        m = re.fullmatch(r"CHAPTER ([IVXL]+)[.,]", h)
        if m:
            chapter, sub, pending_chapter = f"Chapter {m.group(1)}", "", True
            if essay == "Introduction":
                essay = ""
            continue
        m = re.fullmatch(r"(?:(.+?)\.--)?SECTION (\d+)\.", h)
        if m:
            if m.group(1):
                chapter = f"{chapter.split(':')[0]}: {title_case(m.group(1))}"
            pending_chapter, sub = False, f"Section {m.group(2)}"
            continue
        m = re.fullmatch(r"_?Section (\d+)\.--(.+?)_?\.?", h)
        if m:
            sub = f"Section {m.group(1)}: {m.group(2).rstrip('_.')}"
            continue
        if work_id == "controversy" and re.fullmatch(r"[IVXL]+\.", h):
            num = "XI" if h == "XL." else h.rstrip(".")      # "XL." is a typo for XI
            sub = f"Stratagem {num}"
            continue
        if is_caps_heading(s) and "\n" not in s:
            if pending_chapter:
                chapter, pending_chapter = f"{chapter}: {title_case(h)}", False
            else:
                sub = title_case(h)
            continue
        if is_indented(b):
            col.join(section(), b)
            continue
        m = re.match(r"SECTION (\d+)\.\s+", s)        # Counsels and Maxims: "SECTION 5. Another ..."
        if m:
            sub, b = f"Section {m.group(1)}", s[m.end():]
        speaker, text = paragraph(b)
        col.add(section(), text, speaker)
    for t in col.turns:
        t.sensitive = flag_sensitive(t.text, where(t.work_id, t.section))
    return col.turns


# --------------------------------------------------------------------------
# Parsing: The World as Will and Idea (Haldane and Kemp)
# --------------------------------------------------------------------------

BOOK_HEAD = re.compile(r"(FIRST|SECOND|THIRD|FOURTH) BOOK\. (.+)")
SUPP_HEAD = re.compile(r"SUPPLEMENTS TO THE (FIRST|SECOND|THIRD|FOURTH) BOOK\.")
CHAPTER_HEAD = re.compile(r"Chapter ([IVXL]+)\.\s*(.*)", re.S)
PARA_MARK = re.compile(r"§ (\d+)\. ")


def wwi_turns(key: str, raw: str, offset: int = 0) -> list[Turn]:
    cfg = WWI[key]
    src = SOURCES[key]
    blocks = blocks_of(raw)
    start = next(i for i, b in enumerate(blocks) if b.strip() == cfg["start"])
    end = next((i for i, b in enumerate(blocks) if i > start and b.strip() == cfg["end"]), len(blocks))
    col = Collector(dict(work_id="wwi", work=WWI_TITLE, author=PERSONA, translator=src["translator"],
                         source_url=read_url(key), volume=cfg["volume"]))
    part = para = ""

    def section():
        return ", ".join(p for p in (part, para) if p)

    for b in blocks[start:end]:
        s = b.strip()
        one = norm(s)
        if SEPARATOR.match(s) or re.fullmatch(r"\[[^\]]*\]", one):
            continue
        if s.startswith("PREFACE TO THE"):
            part, para = title_case(one), ""
            continue
        if s.startswith("APPENDIX: CRITICISM"):
            part, para = "Appendix: Criticism of the Kantian Philosophy", ""
            continue
        m = BOOK_HEAD.fullmatch(one)
        if m:
            part, para = f"{m.group(1).title()} Book: {title_case(m.group(2))}", ""
            continue
        m = SUPP_HEAD.fullmatch(one)
        if m:
            part, para = f"Supplements to the {m.group(1).title()} Book", ""
            continue
        m = CHAPTER_HEAD.fullmatch(one)
        if m and len(one) < 140:
            title = re.sub(r"^\(\d+\)\s*", "", m.group(2))
            para = f"Chapter {m.group(1)}: {title_case(title)}" if title else f"Chapter {m.group(1)}"
            continue
        if one == "Note On What Has Been Said About Bichat.":
            para = "Note on What Has Been Said About Bichat"
            continue
        # sub-headings that are not Schopenhauer's prose: "First Aspect. ...",
        # "First Half. ...", the dated signatures of the prefaces
        if re.match(r"(First|Second) (Aspect|Half)\.", one) or re.fullmatch(r"_Written at .*_", one):
            continue
        m = re.fullmatch(r"_([A-Z][\w ]{1,20})\._", one)     # "_The Subject._" (dialogue in ch. I)
        if m:
            col.label = m.group(1)
            continue
        if is_indented(b) or (one.startswith("—") and len(one.split()) < 12):
            col.join(section(), b)     # verse quotations and their attributions
            continue
        m = PARA_MARK.match(s)
        if m and part.endswith(("Idea", "Will")) and "Book" in part:
            para = f"§ {m.group(1)}"
            s = s[m.end():]
        col.add(section(), s)
    for t in col.turns:
        t.idx += offset
        t.sensitive = flag_sensitive(t.text, where(t.work_id, t.section))
    return col.turns


# --------------------------------------------------------------------------
# Sensitive flags
# --------------------------------------------------------------------------


def where(work_id: str, section: str) -> str:
    return f"{work_id}|{section}"


def flag_sensitive(text: str, at: str = "") -> list[str]:
    extra = [f for key, fs in SECTION_FLAGS.items() if at == key for f in fs]
    return [k for k, pat in SENSITIVE_PATTERNS.items()
            if k in extra or re.search(pat, text, re.I)]


CONTEXT_WINDOW = 2


def add_suicide_context(turns: list[Turn], passages: list[dict], window: int = CONTEXT_WINDOW) -> set[str]:
    """Flag passages near a discussion of suicide with "suicide_context".

    Schopenhauer's sections are long (a WWI chapter or the essay collections'
    "Psychological Observations" run to many thousands of words), so unlike
    Seneca the flag does not spread over a whole section: it covers the
    passages up to `window` before and after a "suicide" passage in the same
    section, plus every passage of the hand-read SUICIDE_CONTEXT_SECTIONS.
    Turns get the flag when one of their passages has it. Returns the
    sections that got at least one flag."""
    hit_ids: set[int] = set()
    for i, p in enumerate(passages):
        at = where(p["work_id"], p["section"])
        if at in SUICIDE_CONTEXT_SECTIONS:
            hit_ids.add(i)
        if "suicide" in p["sensitive"]:
            for j in range(max(0, i - window), min(len(passages), i + window + 1)):
                if where(passages[j]["work_id"], passages[j]["section"]) == at:
                    hit_ids.add(j)
    flagged_turns: set[tuple[str, int]] = set()
    for i in sorted(hit_ids):
        p = passages[i]
        if "suicide_context" not in p["sensitive"]:
            p["sensitive"].append("suicide_context")
        for k in range(p["turn_range"][0], p["turn_range"][1] + 1):
            flagged_turns.add((p["work_id"], k))
    for t in turns:
        if (t.work_id, t.idx) in flagged_turns and "suicide_context" not in t.sensitive:
            t.sensitive.append("suicide_context")
    return {where(passages[i]["work_id"], passages[i]["section"]) for i in hit_ids}


# --------------------------------------------------------------------------
# SFT
# --------------------------------------------------------------------------

YOU_CUE = r"you (say|ask|reply|object|retort|will say|will ask|will reply|may say|may ask|might say|exclaim|cry)"
# Narrower than the Seneca cues: Schopenhauer often writes "of which it may be
# said: '...'" or "any one might reply: '...'" to quote a lament he then
# develops, not an objection he answers, so those cues are left out.
OTHER_CUE = r"(says|asks|cries|replies|objects) (our|my|the|an?) (adversary|opponent|objector|critic|antagonist)"
CUE = rf"(?P<cue>{YOU_CUE}|{OTHER_CUE})"
QUOTE = re.compile(r"[“\"]([^“”\"]+)[”\"]")
CUE_AFTER = re.compile(rf"^,?\s*{CUE}\b(,? (perhaps|then|again|me))?[,.;:]?\s*", re.I)
CUE_BEFORE = re.compile(rf"\b{CUE}(,? (perhaps|then|again|me))?[,:]?\s*$", re.I)


def find_objections(text: str) -> list[tuple[int, int, str, str]]:
    """(start, end, objection, cue) for each cued quotation, as in the Seneca
    pipeline. `end` is the offset where the answer begins."""
    found = []
    quotes = list(QUOTE.finditer(text))
    i = 0
    while i < len(quotes):
        q = quotes[i]
        after = CUE_AFTER.match(text[q.end():])
        before = CUE_BEFORE.search(text[max(0, q.start() - 40): q.start()])
        if not (after or before):
            i += 1
            continue
        cue = (after or before).group("cue").lower()
        parts, end = [q.group(1)], q.end()
        if after:
            end = q.end() + after.end()
            if i + 1 < len(quotes) and quotes[i + 1].start() == end:
                i += 1
                parts.append(quotes[i].group(1))
                end = quotes[i].end()
        obj = norm(" ".join(re.sub(r",$", "", p.strip()) for p in parts[:-1]) + " " + parts[-1].strip())
        obj = re.sub(r",$", ".", obj)
        found.append((q.start(), end, obj[:1].upper() + obj[1:], cue))
        i += 1
    return found


def first_words(text: str, limit: int) -> str:
    out: list[str] = []
    for sent in re.split(r"(?<=[.?!”])\s+", text):
        w = sent.split()
        if out and len(out) + len(w) > limit:
            break
        out += w
    return " ".join(out[:limit])


def build_sft(turns: list[Turn], min_words: int = 15, max_words: int = 200,
              min_dialogue_words: int = 4) -> list[dict]:
    """Dialogue pairs (interlocutor -> Philalethes) and objection/reply pairs."""
    examples = []
    by_work: dict[str, list[Turn]] = {}
    for t in turns:
        by_work.setdefault(t.work_id, []).append(t)
    section_no: dict[str, int] = {}
    for work_turns in by_work.values():
        for i, t in enumerate(work_turns):
            at = where(t.work_id, t.section)
            section_no.setdefault(at, len([k for k in section_no if k.startswith(t.work_id + "|")]))
            nxt = work_turns[i + 1] if i + 1 < len(work_turns) else None
            # 1. Dialogue: the interlocutor speaks, Philalethes answers.
            if (t.speaker in DIALOGUE_SPEAKERS and t.speaker != "Philalethes" and nxt
                    and nxt.speaker == "Philalethes" and nxt.section == t.section):
                reply = first_words(nxt.text, max_words)
                # "(Aside.) German humbug, he means." is not an answer
                if len(reply.split()) >= min_dialogue_words and not reply.startswith("(Aside"):
                    user = first_words(t.text, max_words)
                    examples.append(_example(nxt, f"{t.speaker}: {user}", reply, "dialogue",
                                             "explicit", section_no[at]))
                continue
            # 2. Objections Schopenhauer puts in an imagined opponent's mouth.
            if t.speaker != PERSONA:
                continue
            objs = find_objections(t.text)
            for j, (start, end, obj, cue) in enumerate(objs):
                if len(obj.split()) < 3:
                    continue
                stop = objs[j + 1][0] if j + 1 < len(objs) else None
                reply = t.text[end:stop].strip().lstrip(";:,—- ")
                if stop is None and len(reply.split()) < min_words and nxt and nxt.section == t.section \
                        and nxt.speaker == PERSONA:
                    reply = norm(reply + " " + nxt.text)
                reply = first_words(reply, max_words)
                if len(reply.split()) < min_words:
                    continue
                examples.append(_example(t, f"Interlocutor: {obj}", reply[:1].upper() + reply[1:],
                                         "objection", "tagged", section_no[at]))
    return examples


def _example(t: Turn, user: str, reply: str, source: str, attribution: str, section_no: int) -> dict:
    at = where(t.work_id, t.section)
    split = "eval" if at in EVAL_SECTIONS or (source == "objection" and section_no % EVAL_EVERY == EVAL_EVERY - 1) \
        else "train"
    return {
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": user},
                     {"role": "assistant", "content": reply}],
        "meta": {"work": t.work, "work_id": t.work_id, "section": t.section,
                 "turn_idx": t.idx, "attribution": attribution, "source": source,
                 "speaker": t.speaker,
                 "is_question": reply.rstrip().endswith("?"),
                 "sensitive": [*flag_sensitive(user + " " + reply, at),
                               *(["suicide_context"] if "suicide_context" in t.sensitive else [])],
                 "split": split, "source_url": t.source_url},
    }


# --------------------------------------------------------------------------
# RAG passages
# --------------------------------------------------------------------------


def split_words(text: str, limit: int) -> list[str]:
    """Pieces of at most `limit` words, cut at sentence ends where possible."""
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
    """Schopenhauer's own prose carries no label; dialogue speakers do."""
    return "" if t.speaker == PERSONA else f"{t.speaker}: "


def build_passages(turns: list[Turn], target_words: int) -> list[dict]:
    """Group paragraphs into passages of at most `target_words` words. Passages
    never cross a section, so `section` is always exact."""
    passages = []
    buf: list[tuple[Turn, str]] = []
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
                lines.append(speaker_label(t) + piece)
        text = "\n".join(lines)
        f = buf[0][0]
        # Content-based id: stable when the corpus is rebuilt.
        pid, n = None, 0
        while pid is None or pid in used:
            salt = f"\0{n}" if n else ""
            pid = f"{f.work_id}-{hashlib.sha256((text + salt).encode('utf-8')).hexdigest()[:8]}"
            n += 1
        used.add(pid)
        passages.append({
            "id": pid, "work_id": f.work_id,
            "author": f.author, "work": f.work, "translator": f.translator,
            "section": f.section, "turn_range": [f.idx, buf[-1][0].idx],
            "speakers": sorted({t.speaker for t, _ in buf}),
            "schopenhauer_words": sum(len(p.split()) for t, p in buf if t.speaker in PERSONA_VOICES),
            "speaker_uncertain": False,
            "volume": f.volume,
            "sensitive": flag_sensitive(text, where(f.work_id, f.section)),
            "source_url": f.source_url,
            "text": text,
        })
        buf.clear()

    for t in turns:
        if buf and (t.work_id != buf[0][0].work_id or t.section != buf[0][0].section
                    or t.source_url != buf[0][0].source_url):
            flush()
            size = 0
        label = len(speaker_label(t).split())
        for piece in split_words(t.text, target_words - label):
            n = len(piece.split()) + label
            if buf and size + n > target_words:
                flush()
                size = 0
            buf.append((t, piece))
            size += n
    flush()
    return passages


CAUTION_FLAGS = ("suicide", "suicide_context", "despair", "prejudice")


def write_caution_csv(path: Path, passages: list[dict]) -> int:
    """Passages for Christopher's tier-2 caution list (persona config, keyed by chunk_id)."""
    n = 0
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["chunk_id", "priority", "work", "volume", "section", "flags", "excerpt"])
        for p in passages:
            if any(fl in p["sensitive"] for fl in CAUTION_FLAGS):
                # high: the passage itself names suicide or devalues life;
                # medium: it sits next to such a passage, or is prejudice
                high = any(fl in p["sensitive"] for fl in ("suicide", "despair"))
                w.writerow([f"schopenhauer-{p['id']}", "high" if high else "medium", p["work"],
                            p["volume"], p["section"], ",".join(p["sensitive"]), p["text"][:200].replace("\n", " ")])
                n += 1
    return n


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


def load_turns(raw_dir: Path, want: set[str]) -> list[Turn]:
    turns: list[Turn] = []
    if not want or "wwi" in want:
        for key in WWI:
            s = SOURCES[key]
            try:
                raw = fetch(raw_url(key), raw_dir / key / s["file"]).decode(s["encoding"])
                turns.extend(wwi_turns(key, raw, offset=sum(t.work_id == "wwi" for t in turns)))
            except Exception as e:  # noqa: BLE001
                print(f"[warn] {key}: {e}", file=sys.stderr)
    for wid in ESSAYS:
        if want and wid not in want:
            continue
        s = SOURCES[wid]
        try:
            raw = fetch(raw_url(wid), raw_dir / wid / s["file"]).decode(s["encoding"])
            turns.extend(essay_turns(wid, raw))
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {wid}: {e}", file=sys.stderr)
    return turns


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("data/processed/schopenhauer"))
    ap.add_argument("--raw", type=Path, default=Path("data/raw/schopenhauer"),
                    help="download cache (git-ignored)")
    ap.add_argument("--works", nargs="*", help="work ids to include: wwi and/or essay ids (default: all)")
    ap.add_argument("--min-words", type=int, default=15, help="min words for an objection reply")
    ap.add_argument("--max-words", type=int, default=200, help="max words for an SFT reply")
    ap.add_argument("--passage-words", type=int, default=180,
                    help="max words per RAG passage (the embedding model reads ~256 tokens)")
    args = ap.parse_args(argv)

    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    turns = load_turns(args.raw, set(args.works or []))

    passages = build_passages(turns, args.passage_words)
    context_sections = add_suicide_context(turns, passages)
    n_turns = write_jsonl(out / "turns.jsonl", (asdict(t) for t in turns))
    sft = build_sft(turns, args.min_words, args.max_words)
    n_sft = write_jsonl(out / "schopenhauer_sft.jsonl", sft)
    n_pass = write_jsonl(out / "rag_passages.jsonl", passages)
    n_caution = write_caution_csv(out / "caution_candidates.csv", passages)
    (out / "stats.json").write_text(json.dumps(
        {"source": {k: {"repo": v["repo"], "commit": v["commit"], "file": v["file"]}
                    for k, v in SOURCES.items()},
         "turns": n_turns, "sft_examples": n_sft,
         "sft_split": {k: sum(e["meta"]["split"] == k for e in sft) for k in ("train", "eval")},
         "sft_source": {k: sum(e["meta"]["source"] == k for e in sft) for k in ("dialogue", "objection")},
         "passages": n_pass,
         "passage_flags": {k: sum(k in p["sensitive"] for p in passages)
                           for k in [*SENSITIVE_PATTERNS, "suicide_context"]},
         "caution_candidates": n_caution,
         "suicide_context_sections": sorted(context_sections),
         "works": summarize(turns)},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"turns={n_turns} sft={n_sft} passages={n_pass} caution={n_caution} -> {out}")
    return 0


def summarize(turns: list[Turn]) -> dict:
    report: dict[str, dict] = {}
    for t in turns:
        r = report.setdefault(t.work_id, {"work": t.work, "translator": t.translator,
                                          "sections": set(), "paragraphs": 0,
                                          "schopenhauer_words": 0, "total_words": 0})
        r["sections"].add(t.section)
        r["paragraphs"] += 1
        r["total_words"] += t.words
        r["schopenhauer_words"] += t.words if t.speaker in PERSONA_VOICES else 0
    for r in report.values():
        r["sections"] = len(r["sections"])
    return report


if __name__ == "__main__":
    sys.exit(main())
