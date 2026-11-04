#!/usr/bin/env python3
"""Philocafe · Montaigne corpus pipeline.

Downloads the public-domain English Essays of Montaigne (tr. Charles Cotton,
1685-1686, revised by William Carew Hazlitt, 1877), strips everything that is
not Montaigne's text (Hazlitt's preface and Life, editorial notes, citations
and the Project Gutenberg apparatus), replaces untranslated Latin, Greek,
Italian and French quotations with their English translations, splits the
Essays and Montaigne's letters into paragraphs, and writes the same three
JSONL files as the Socrates and Seneca pipelines, so build_sqlite.py and
retrieval.py work as is:

  turns.jsonl          one record per paragraph ("turn")
  montaigne_sft.jsonl  chat-format examples where Montaigne is the assistant
  rag_passages.jsonl   passages of at most ~180 words with citations, for retrieval

Montaigne wrote essays, not dialogues, so a "turn" is one paragraph in his
voice, and SFT examples come from the objections he puts in an imagined
reader's mouth ("you will say ...") and his answer, as for Seneca. See
docs/montaigne.md for the reasoning and for copyright notes.

Source: Project Gutenberg eBook #3600 (HTML edition by David Widger), via the
GITenberg mirror on GitHub, pinned to a commit. Standard Ebooks has no
Montaigne edition, and gutenberg.org is not reachable from every machine.

Only the Python standard library is used. Run from the repository root:

    python3 scripts/montaigne_pipeline.py
    python3 scripts/montaigne_pipeline.py --with-topic-prompts
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
import urllib.request
from dataclasses import dataclass, field, asdict
from html.parser import HTMLParser
from pathlib import Path

# --------------------------------------------------------------------------
# Source configuration
# --------------------------------------------------------------------------

# Pinned to a commit so that upstream changes cannot silently change the
# output. The commit is also recorded in stats.json.
SOURCE = dict(
    repo="GITenberg/Essays-of-Michel-de-Montaigne---Complete_3600",
    commit="a538bae9d1e50ebf51938c73c484ee6ab3824c18",
    path="3600-h/3600-h.htm",
    gutenberg_ebook=3600,
    translator="Charles Cotton (rev. William Carew Hazlitt)",
)


def raw_url() -> str:
    return f"https://raw.githubusercontent.com/{SOURCE['repo']}/{SOURCE['commit']}/{SOURCE['path']}"


def read_url(anchor: str = "") -> str:
    # Citation link shown to users: the same pinned file served by jsDelivr,
    # with the chapter's anchor so the browser jumps to the right essay.
    url = f"https://cdn.jsdelivr.net/gh/{SOURCE['repo']}@{SOURCE['commit']}/{SOURCE['path']}"
    return f"{url}#{anchor}" if anchor else url


PERSONA = "Montaigne"
WORK_ESSAYS = "Essays"
WORK_LETTERS = "Letters"

SYSTEM_PROMPT = (
    "You are Michel de Montaigne, the sixteenth-century French essayist, "
    "talking with a friend. You do not lay down doctrine: you try ideas out "
    "on yourself, speak from your own habits, moods and weaknesses, weigh "
    "examples from history and the ancients on both sides of a question, "
    "admit what you do not know, and leave the other person freer to judge "
    "for themselves."
)

# Chapter titles in the source are in capitals and have a few typos; the
# fixed titles below replace the automatic title case.
TITLE_FIXES = {
    "That the Hour of Parley Dangerous": "That the Hour of Parley Is Dangerous",
    "That to Study Philosopy Is to Learn to Die": "That to Study Philosophy Is to Learn to Die",
    "Of the Inequality Amoungst Us": "Of the Inequality Amongst Us",
    "Nine and Twenty Sonnets of Estienne de la Boitie": "Nine and Twenty Sonnets of Estienne de la Boetie",
    "Apology for Raimond Sebond": "Apology for Raimond Sebond",
}
SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of",
               "on", "or", "the", "to", "upon", "with", "de", "la"}

# Passages touching on these themes are flagged so they can be reviewed and
# handled with care. Montaigne discusses suicide openly (Book II, Chapter III,
# "A Custom of the Isle of Cea", is an essay about it; also the deaths of
# Cato and of the "three good women" in II.35), meditates on death throughout
# (I.19 "That to Study Philosophy Is to Learn to Die"), and writes about his
# kidney stones and pain. Flags are hints for corpus analysis, not a filter;
# retrieval does not use them (design doc v0.2, section 7.1).
_POSS = r"(his|her|their|one's|one’s|my|your|our)"
SENSITIVE_PATTERNS = {
    "suicide": (
        r"\b(suicides?|self-destruction|self-murder|kill(ed|s|ing)? (him|her|my|your|them|one|our)sel(f|ves)"
        rf"|(take|took|taking|takes|end|ended|ending|ends|shorten|shortened) {_POSS} (own )?li(fe|ves)"
        r"|(lay|lays|laid|laying) violent hands (up)?on (him|her|them|my|your|one|our)sel(f|ves)"
        r"|(slay|slew|slain|destroy|destroyed|dispatch|dispatched|despatch|despatched) (him|her|them|my|your|one|our)sel(f|ves)"
        rf"|(open|opens|opened|opening|cut) {_POSS} veins"
        rf"|(die|dies|died|perish|perished|fell) by {_POSS} own hands?"
        rf"|(by|with) {_POSS} own hands? (to )?(die|death)"
        rf"|(choose|chose|chooses|choosing|hasten|hastened|procure|procured) {_POSS} (own )?(death|end)"
        r"|voluntary death|(voluntarily|willingly) (to )?die|die voluntarily"
        r"|(deliver|delivered|rid|free|freed|release|released) (him|her|them|my|your|one|our)sel(f|ves) (from|of) (life|this life)"
        r"|(leave|leaves|left|leaving|quit|quits|quitting|depart|departs|departing|go out of) (this )?life (when|whenever|at)"
        r"|(threw|throw|throws|cast|casts|precipitated|precipitate) (him|her|them|my|your|one|our)sel(f|ves) "
        r"(from|headlong|off|into the (sea|river|fire|flames|well))"
        r"|starv(e|ed|es|ing) (him|her|them|your|my|one)sel(f|ves)|starv(e|ed|ing) to death"
        r"|(abstain|abstained|abstaining|refused?) (from )?(food|all nourishment|to eat)"
        r"|(hang|hanged|hung|strangled|poisoned|stabbed) (him|her|them|my|your|one|our)sel(f|ves)"
        r"|(sword|dagger|poniard|knife) (in|into|through) (his|her|their) own"
        r"|desire to die|longing for death|seek(s|ing)? death)\b"),
    "death": r"\b(death|dying|die|dies|died|corpse|hemlock|poison(ed)?|executed?|execution|funeral)\b",
    "violence": (r"\b(murder(ed|er|s)?|slay|slain|slaughter(ed)?|massacre[ds]?|beat(en)?|scourg(e|ed|ing)"
                 r"|tortur(e|ed|es)|torments?|crucif\w*|the rack|cannibals?|eat(ing)? (human|men's) flesh)\b"),
    # Of Sorrow (I.2), the death of La Boetie (Letter I, I.27), his daughters.
    "grief": r"\b(grief|griefs|griev(e|es|ed|ing)|mourn(s|ed|ing)?|bereave(d|ment)|sorrow(s)?)\b",
    # Montaigne describes his kidney stones and pain at length (II.37, III.13).
    "illness": r"\b(the stone|the gravel|colic|disease[ds]?|sickness|maladies|malady|physicians?|pain(s|ful)?)\b",
    # Upon Some Verses of Virgil (III.5) is mostly about sex and marriage.
    "sexuality": r"\b(lovers?|sexual|venery|venereal|adulter(y|er|ers|ess)|lust|cuckold\w*|fornicat\w*|the act of love)\b",
}

# Keys below are "<work_id>|<section prefix>". A key ending in ":" matches any
# section that starts with it ("essays|Book II, Chapter III:").
#
# A Custom of the Isle of Cea is an essay on suicide, and many of its
# passages use wording the regex misses ("to make his exit", "the door").
SECTION_FLAGS = {
    "essays|Book II, Chapter III:": ["suicide"],
}
# Sections that discuss suicide somewhere, read by hand, in addition to every
# section where the suicide pattern matches at least once. All passages in
# these sections get "suicide_context".
SUICIDE_CONTEXT_SECTIONS = (
    "essays|Book I, Chapter XIX:",    # philosophy is learning to die; "the door is open"
    "essays|Book II, Chapter XIII:",  # judging the death of another; Cato, the deaths of the ancients
    "essays|Book II, Chapter XXXV:",  # three wives who die with or for their husbands
    "essays|Book I, Chapter XXXVI:",  # Cato the Younger
)

# SFT examples held out as an eval split: every tenth chapter of each book
# (I.10, I.20, ... II.10, ... III.10), whole, so neighbouring examples never
# land on both sides of the split.
EVAL_CHAPTER_EVERY = 10

# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------


@dataclass
class Turn:
    # Same fields as the Socrates/Seneca Turn (build_sqlite.py ignores keys
    # it does not know).
    work_id: str
    work: str
    author: str
    translator: str
    source_url: str
    section: str          # "Book I, Chapter XIX: That to Study Philosophy Is to Learn to Die"
    idx: int              # running paragraph index within the work
    speaker: str          # always "Montaigne"
    kind: str             # speech (the essayist's own prose)
    attribution: str      # explicit: the author of the paragraph is never in doubt
    text: str
    addressee: str = ""
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


def norm(s: str) -> str:
    s = s.replace(" ", " ").replace("⁠", "")
    s = re.sub(r"\s+", " ", s)
    # tidy what is left after removing notes: "Tyrant, who", "rock— “..."
    s = re.sub(r"\s+([,.;:?!)])", r"\1", s)
    s = re.sub(r"([,;:])(?=[^\s\d”’])", r"\1 ", s)
    s = re.sub(r"—\s*—+", "—", s)
    s = re.sub(r"([,;:])\s*—\s*(?=[a-z])", r"\1 ", s)
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def roman_to_int(s: str) -> int:
    vals = dict(I=1, V=5, X=10, L=50, C=100)
    n = 0
    for a, b in zip(s, s[1:] + " "):
        v = vals[a]
        n += -v if vals.get(b, 0) > v else v
    return n


def title_case(caps: str) -> str:
    words = caps.strip(" .").lower().split()
    out = []
    for i, w in enumerate(words):
        if i and w in SMALL_WORDS:
            out.append(w)
        else:
            out.append("-".join(p[:1].upper() + p[1:] for p in w.split("-")))
    t = " ".join(out).replace("’S", "’s")
    return TITLE_FIXES.get(t, t)


# Very small language test for quotations: Hazlitt prints the Latin (or
# Greek, Italian, French) original and adds an English translation in
# brackets. Untranslated originals are dropped; English is kept.
_EN = set("the and of to is that his with for they are was which this but have from all what "
          "who thy thou thee doth hath be by he it my our we you shall will when if how not "
          "their them were has had would should than then there so him her its".split())
_FOREIGN = set("et est non quod sed nec ut cum qui quae quam enim atque ad sunt esse nihil neque "
               "hoc quid ac vel aut sic tam ab ex si ipse omnia omnes nam etiam magis nunc tamen "
               "mihi sibi tibi nos vos te se ille illa haec ita vita mors animus animi "
               "il la le les des du que qui di che non per una uno della".split())


_EN_COMMON = set("i a me us go let sir men man best do must no yes truly she yourself myself away "
                 "said say says drink die dead live life love god lord good evil time day night come "
                 "see make made take give know think great little more most much many one two first "
                 "now here only well very like may can could might never ever always nothing every "
                 "an at in on up out off over under upon after before again o oh alas".split())
_LATIN_END = re.compile(r"(us|um|ae|is|que|ibus|orum|arum|ant|unt|ent|it|em|am|os|as|ii|io|ior|ius|ere|are|ire|o)$")


def is_english(s: str) -> bool:
    words = re.findall(r"[a-zA-Z’']+", s.lower())
    en = sum(w in _EN for w in words)
    fo = sum(w in _FOREIGN for w in words)
    return en > 0 and en >= fo


def is_foreign(s: str) -> bool:
    """True for a quotation that is clearly not English."""
    words = re.findall(r"[a-zA-Z’']+", s.lower())
    if not words:
        return False
    en = sum(w in _EN for w in words)
    fo = sum(w in _FOREIGN for w in words)
    if en == 0:
        if fo > 0:
            return True
        # no function word either way ("Diriguisse malis", "Lame men perform
        # best."): foreign only if most words have Latin endings and none
        # is a common English word
        if any(w in _EN_COMMON for w in words):
            return False
        latin = sum(bool(_LATIN_END.search(w)) for w in words)
        return latin * 2 >= len(words) + 1
    return fo > 2 * en


OPEN_Q, CLOSE_Q = "“", "”"
# <i>...</i> is kept as markers through parsing: the Apology prints its
# Latin quotations in italics, followed by the English in quotation marks.
ITAL_ON, ITAL_OFF = "\u0001", "\u0002"


# Signatures of the editors' notes (Coste, Le Clerc, Naigeon, Ampère, Widger).
_EDITOR_NOTE = re.compile(r"\b(Coste|Le ?Clerc|Naigeon|Ampere|Ampère|D\.W\.)(?=\W|$)")


def translation_of(note: str) -> str | None:
    """The English translation in a bracketed note, without the citation:
    '“Petrified with her misfortunes.”—Ovid, Met., vi. 304.' ->
    '“Petrified with her misfortunes.”'. None if the note is not a translation."""
    note = note.strip()
    if not note.startswith((OPEN_Q, '"', "‘")):
        # "[ Many brave men lived ... unknown.”—Horace, Od., iv. 9, 25.]":
        # the opening quotation mark is missing in a few places
        m = re.match(r"^([^“”\[\]]{3,600})”\s*—", note)
        if not m or "Montaigne" in m.group(1):
            return None
        note = OPEN_Q + note
    end = note.rfind(CLOSE_Q)
    dash = note.find("—")
    if end <= 0 or (dash > 0 and dash < end and CLOSE_Q not in note[:dash]):
        # no closing quote before the citation: cut at the citation dash
        body = note[1:dash] if dash > 0 else note[1:]
    else:
        body = note[1:end]
    tail = note[end + 1:] if end > 0 else ""
    if _EDITOR_NOTE.search(tail) or "Montaigne" in body:
        return None                      # an editor's note that happens to be quoted
    body = re.sub(r"\s*[—-]+\s*$", "", body.strip())
    body = body.strip(" “”\"")
    return f"{OPEN_Q}{body}{CLOSE_Q}" if body else None


def _bracket_spans(text: str) -> list[tuple[int, int, str]]:
    """Top-level [..] groups (with nested [..] and {..}), widened over the
    dashes Hazlitt puts around inline notes ("—[ ... ]—")."""
    spans, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        if ch in "[{":
            if depth == 0:
                start = i
            depth += 1
        elif ch in "]}" and depth:
            depth -= 1
            if depth == 0:
                spans.append((start, i + 1, text[start + 1:i]))
    out = []
    for s, e, inner in spans:
        while s > 0 and text[s - 1] in "—-":
            s -= 1
        while e < len(text) and text[e] in "—-":
            e += 1
        out.append((s, e, inner))
    return out


_PREV_QUOTE = re.compile(r"“([^“”]{1,1500})”[,.;:!?]?\s*$")


def clean_text(text: str, stats: dict | None = None) -> str:
    """Remove editorial notes and replace foreign quotations by their
    bracketed English translations; drop untranslated foreign quotations."""
    stats = stats if stats is not None else {}
    out, pos = "", 0
    for s, e, inner in _bracket_spans(text):
        out += text[pos:s]
        pos = e
        tr = translation_of(inner)
        if tr is None:
            stats["notes_removed"] = stats.get("notes_removed", 0) + 1
            out += " "
            continue
        m = _PREV_QUOTE.search(out)
        if m and not is_english(m.group(1)):
            out = out[:m.start()]
            stats["quotes_translated"] = stats.get("quotes_translated", 0) + 1
        elif m:
            # the original is already English: keep it, drop the note
            stats["notes_removed"] = stats.get("notes_removed", 0) + 1
            out += " "
            continue
        else:
            stats["translations_inserted"] = stats.get("translations_inserted", 0) + 1
        out += " " + tr + " "
    out += text[pos:]

    # untranslated foreign quotations that remain
    def drop(m: re.Match) -> str:
        if is_foreign(m.group(1)) and len(m.group(1).split()) >= 2:
            stats["foreign_dropped"] = stats.get("foreign_dropped", 0) + 1
            return " "
        return m.group(0)
    out = re.sub(r"\s*\([^()]*\bD\.\s?W\.\)", " ", out)      # "(... D.W.)": Widger's notes
    out = re.sub(r"[^.;:]*\bthus translated by Cotton:", " ", out)
    out = re.sub(r"“([^“”]{1,1500})”", drop, out)
    out = re.sub(f"{ITAL_ON}([^{ITAL_ON}{ITAL_OFF}]*){ITAL_OFF}", drop, out)
    return norm(out.replace(ITAL_ON, "").replace(ITAL_OFF, ""))


# --------------------------------------------------------------------------
# Parsing (Project Gutenberg HTML)
# --------------------------------------------------------------------------


class _Blocks(HTMLParser):
    """Flatten the HTML into (tag, text, anchor) for h1/h2/h3/p/pre, in order.
    `anchor` is the last <a name=...> seen, used for source_url fragments."""
    BLOCKS = ("h1", "h2", "h3", "p", "pre")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str, str]] = []
        self.cur: str | None = None
        self.buf: list[str] = []
        self.anchor = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("name"):
            self.anchor = a["name"]
        if tag in self.BLOCKS:
            self.cur, self.buf = tag, []
        elif tag == "br" and self.cur:
            self.buf.append("\n")
        elif tag == "i" and self.cur:
            self.buf.append(ITAL_ON)

    def handle_endtag(self, tag):
        if tag == "i" and self.cur:
            self.buf.append(ITAL_OFF)
        if tag == self.cur:
            self.blocks.append((tag, "".join(self.buf), self.anchor))
            self.cur = None

    def handle_data(self, data):
        if self.cur:
            self.buf.append(data)


def parse_blocks(page: str) -> list[tuple[str, str, str]]:
    p = _Blocks()
    p.feed(page)
    return p.blocks


def _strip_citation(s: str) -> str:
    """Drop a trailing citation line ("—Horace, Ep., i. 14, 13.")."""
    return re.sub(r"\s*—\s*[A-Z][^“”—]{0,60}$", "", s) if "—" in s[-60:] else s


def pre_text(raw: str) -> str:
    """A <pre> block holds a verse quotation, in one of two layouts:

      original, then '[“translation”—citation]'   (most chapters)
      original, blank line, '“translation”'        (Apology for Raimond Sebond)

    or an English verse, or a stray note. Returns the text that belongs in
    Montaigne's paragraph: the English stanza(s) if there are any, else the
    bracketed translation; untranslated foreign verse is dropped."""
    raw = html.unescape(raw).replace(ITAL_ON, "").replace(ITAL_OFF, "").strip("\n")
    out: list[str] = []

    def body(seg: str):
        for stanza in re.split(r"\n\s*\n", seg):
            st = norm(re.sub(r"\.{5,}", " ", stanza))    # "......." lacunae lines
            if st and is_english(st) and not is_foreign(st):
                out.append(_strip_citation(st))

    pos = 0
    for s, e, inner in _bracket_spans(raw):
        body(raw[pos:s])
        pos = e
        inner = norm(inner)
        tr = translation_of(inner)
        if tr is None and not _EDITOR_NOTE.search(inner) and "Montaigne" not in inner:
            # "[Seneca, Ep., 95. “Since the ‘savans’ ... eclipsed.” —Rousseau]":
            # a citation first, then the translation
            q = re.search(r"“[^“”]+”", inner)
            tr = q.group(0) if q else None
        if tr:
            out.append(tr)
    body(raw[pos:])
    return " ".join(out)


# Who each letter is written to (the headings give only titles).
LETTER_ADDRESSEES = {
    "I": "his father", "II": "his father", "III": "M. de Lansac", "IV": "M. de Mesmes",
    "V": "M. de L’Hospital", "VI": "M. de Foix", "VII": "his wife", "VIII": "M. Dupuy",
    "IX": "the Jurats of Bordeaux", "X": "the Jurats of Bordeaux", "XI": "the Jurats of Bordeaux",
    "XIII": "Mademoiselle Paulmier", "XIV": "King Henry IV", "XV": "King Henry IV",
    "XVI": "the Governor of Guienne",
}

_CHAPTER = re.compile(r"^CHAPTER ([IVXLC]+)\.?\s*[—–-]+\s*(.+)$")
_LETTER = re.compile(r"^([IVXLC]+)\.(?:\s*[—–-]+\s*(.+))?$")
_BOOK = re.compile(r"^BOOK THE (FIRST|SECOND|THIRD)$")
BOOKS = {"FIRST": "I", "SECOND": "II", "THIRD": "III"}


def parse_montaigne(page: str, stats: dict | None = None) -> list[Turn]:
    """Turns for Montaigne's letters and the Essays, in book order."""
    stats = stats if stats is not None else {}
    turns: list[Turn] = []
    region = None           # None (front matter), "letters", "essays", "end"
    book, section, addressee, anchor = "I", "", "", ""
    work_id = ""
    join_next = False

    def start(wid: str, sec: str, anc: str, addr: str = ""):
        nonlocal work_id, section, anchor, addressee, join_next
        work_id, section, anchor, addressee, join_next = wid, sec, anc, addr, False

    def add(text: str, continues: bool):
        if not text:
            return
        t_prev = turns[-1] if turns else None
        if continues and t_prev and t_prev.section == section and t_prev.work_id == work_id:
            t_prev.text = norm(t_prev.text + " " + text)
            t_prev.words = len(t_prev.text.split())
            return
        idx = sum(t.work_id == work_id for t in turns)
        turns.append(Turn(work_id=work_id,
                          work=WORK_ESSAYS if work_id == "essays" else WORK_LETTERS,
                          author="Michel de Montaigne", translator=SOURCE["translator"],
                          source_url=read_url(anchor), section=section, idx=idx,
                          speaker=PERSONA, kind="speech", attribution="explicit",
                          text=text, addressee=addressee))

    for tag, raw, anc in parse_blocks(page):
        head = norm(html.unescape(raw))
        plain = head.replace(ITAL_ON, "").replace(ITAL_OFF, "")
        if tag in ("h1", "h2", "pre"):
            head = plain
        if tag in ("h1", "h2"):
            if head.startswith(("PREFACE", "THE LIFE OF MONTAIGNE")):
                region = None
                continue
            if head.startswith(("APOLOGY:", "PROJECT GUTENBERG")):
                region = "end"
                continue
            if region == "end":
                continue
            m = _BOOK.match(head)
            if m:
                book = BOOKS[m.group(1)]
                region = "essays"
                continue
            m = _CHAPTER.match(head)
            if m and region == "essays":
                start("essays", f"Book {book}, Chapter {m.group(1)}: {title_case(m.group(2))}", anc)
                continue
            m = _LETTER.match(head)
            if m and region == "letters":
                to = (m.group(2) or "").strip(" .,")
                to = re.sub(r"\b(?![IVX]+\b)[A-Z’']{2,}\b",
                            lambda w: w.group(0).title().replace("’S", "’s"), to)
                addr = LETTER_ADDRESSEES.get(m.group(1), "")
                sec = f"Letter {m.group(1)}" + (f": {to}" if to else "")
                start("letters", sec, anc, addr)
                continue
            continue
        if tag == "pre":
            if head.startswith("THE LETTERS OF MONTAIGNE"):
                region = "letters"
                continue
            if head.startswith("THE AUTHOR TO THE READER"):
                region = "essays"
                book = "I"
                start("essays", "To the Reader", anc, "Reader")
                continue
            if region not in ("letters", "essays") or not section:
                continue
            text = clean_text(pre_text(raw), stats)
            stats["verse_blocks"] = stats.get("verse_blocks", 0) + 1
            if not text:
                stats["verse_blocks_dropped"] = stats.get("verse_blocks_dropped", 0) + 1
            add(text, True)
            join_next = True
            continue
        if region not in ("letters", "essays") or not section:
            continue
        if tag == "h3":
            # dedications ("TO MADAME DIANE DE FOIX") and the repeated title
            # page are not prose; two chapters open with an h3 sentence
            if (head.upper().startswith("TO ") or "Translated by" in head
                    or "Edited by" in head or head.strip(".") == "1877" or head.isupper()):
                continue
            add(clean_text(head, stats), False)
            join_next = True
            continue
        # <p>
        if not head:
            continue
        starts_note = head.startswith(("[", "—[", "{"))
        text = clean_text(head, stats)
        if not text:
            continue
        if work_id == "letters" and len(text.split()) < 15 and re.search(r"\bMONTAIGNE\b", text):
            continue                     # signature: "Your humble servant, MONTAIGNE."
        cont = join_next and (text[:1].islower() or starts_note or text[:1] in ",;:)")
        if (text[:1].islower() or text[:1] in ",;:") and not join_next:
            cont = True
        add(text, cont)
        join_next = False
        # a paragraph that ends with ":" or "—" introduces a quotation
    for t in turns:
        t.text = t.text[:1].upper() + t.text[1:] if t.text[:1] == "“" else t.text
        t.sensitive = flag_sensitive(t.text, where(t.work_id, t.section))
    return turns


# --------------------------------------------------------------------------
# Sensitive content
# --------------------------------------------------------------------------


def where(work_id: str, section: str) -> str:
    return f"{work_id}|{section}"


def in_sections(at: str, keys) -> bool:
    return any(at == k or (k.endswith(":") and at.startswith(k)) for k in keys)


def flag_sensitive(text: str, at: str = "") -> list[str]:
    extra = [f for key, fs in SECTION_FLAGS.items() if in_sections(at, [key]) for f in fs]
    return [k for k, pat in SENSITIVE_PATTERNS.items()
            if k in extra or re.search(pat, text, re.I)]


def add_suicide_context(turns: list[Turn], passages: list[dict], window: int = 2) -> set[str]:
    """Flag passages near a suicide passage, and whole hand-picked sections.

    Seneca's pipeline flags whole sections. Montaigne's chapters are much
    longer (the Apology for Raimond Sebond alone is ~400 passages), so a
    section-level flag would cover most of the book. Here a passage gets
    "suicide_context" when it is within `window` passages of a "suicide"
    passage in the same section, or when its section is listed in
    SUICIDE_CONTEXT_SECTIONS / SECTION_FLAGS. Turns get the flag when one
    of their passages has it. Returns the sections that have any flag."""
    whole = set(SUICIDE_CONTEXT_SECTIONS) | set(SECTION_FLAGS)
    marked = set()
    for i, p in enumerate(passages):
        at = where(p["work_id"], p["section"])
        if in_sections(at, whole):
            marked.add(i)
        if "suicide" in p["sensitive"]:
            for k in range(max(0, i - window), min(len(passages), i + window + 1)):
                if where(passages[k]["work_id"], passages[k]["section"]) == at:
                    marked.add(k)
    hit_turns: set[tuple[str, int]] = set()
    sections: set[str] = set()
    for i in sorted(marked):
        p = passages[i]
        if "suicide_context" not in p["sensitive"]:
            p["sensitive"].append("suicide_context")
        sections.add(where(p["work_id"], p["section"]))
        for idx in range(p["turn_range"][0], p["turn_range"][1] + 1):
            hit_turns.add((p["work_id"], idx))
    for t in turns:
        if (t.work_id, t.idx) in hit_turns and "suicide_context" not in t.sensitive:
            t.sensitive.append("suicide_context")
    return sections


# --------------------------------------------------------------------------
# SFT: objection -> reply pairs
# --------------------------------------------------------------------------

# Cues that mark a quotation as an imagined reader's objection, not a
# quotation of a poet or a historical saying.
# "says one" / "says another" are left out: in Montaigne they introduce poets
# and ancients ("'Let Cato ... be greater than Caesar,' says one"), and "if
# you say" is a hypothetical, not an objection.
YOU_CUE = (r"(?<!that )(?<!if )you (say|ask|reply|object|retort|will say|will ask|will reply|will tell me|may say|may ask"
           r"|might say|will object|exclaim|cry)|will you say|you'?ll say")
OTHER_CUE = (r"(says|asks|cries|replies|objects) (our|my|the|an?) (adversary|opponent|objector|critic|antagonist)"
             r"|(one|some one|someone|somebody|some|any one|another) (may|might|will|would) (say|ask|object|reply|tell me)"
             r"|(will|may) (some|any) one say"
             r"|it (may|might|will) be (said|asked|objected|answered)")
CUE = rf"(?P<cue>{YOU_CUE}|{OTHER_CUE})"
QUOTE = re.compile(r"“([^“”]+)”")
CUE_AFTER = re.compile(rf"^,?\s*{CUE}\b(,? (perhaps|then|again|me))?[,.;:?]?\s*", re.I)
CUE_BEFORE = re.compile(rf"\b{CUE}(,? (perhaps|then|again|me))?[,:]?\s*(that\s*)?$", re.I)


def find_objections(text: str) -> list[tuple[int, int, str, str]]:
    """Return (start, end, objection, cue) for each cued quotation in text.
    Split quotations ("'But,' you will say, 'why ...?'") are joined. `end` is
    the offset where Montaigne's answer begins."""
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
        obj = obj[:1].upper() + obj[1:]
        found.append((q.start(), end, obj, cue))
        i += 1
    return found


# Cotton usually prints the reader's objection without quotation marks:
# "What matter is it, you will say, which way it comes to pass ...?",
# "You will say, there is vanity in this way of living."
UNQUOTED_CUE = re.compile(
    r"(?:^|(?<=[,;:] )|(?<=^well, but )|(?<=^but ))"
    r"(?P<cue>you will say|you may say|you will tell me|some ?one will say(?: to me)?|some will say"
    r"|will you say|it will be said|it may be said"
    r"|it may(?:, peradventure,)? be objected(?: against me)?|you will object)"
    r"(?:,| that|:|(?=[.?]))\s*", re.I)


def find_unquoted_objections(text: str) -> list[tuple[int, int, str, str]]:
    """Objections in a sentence that carries an unquoted cue. The objection
    is the sentence without the cue; Montaigne's answer starts after it."""
    found = []
    for m in re.finditer(r"[^.?!]+[.?!]+[”’]?", text):
        sent = m.group(0)
        if "“" in sent or "”" in sent:
            continue                     # quoted ones are handled by QUOTE
        lead = len(sent) - len(sent.lstrip())
        body = sent.strip()
        c = UNQUOTED_CUE.search(body)
        if not c:
            continue
        before = body[:c.start()].rstrip(" ,;:")
        before = re.sub(r"^(well, but|but|well)$", "", before, flags=re.I).strip()
        before = re.sub(r"^(well, but|but) ", "", before, flags=re.I)
        after = body[c.end():].strip()
        cut = None
        if not before and ";" in after:
            # "You will tell me that he was a braggadocio; I believe so too":
            # the objection ends at the first semicolon, the answer follows
            after, rest = after.split(";", 1)
            cut = m.end() - len(rest) - (len(sent) - len(sent.rstrip()))
        obj = norm(f"{before} {after}" if before and after and not before.endswith(("?", ".")) else
                   (before or after))
        obj = obj.rstrip(",;: ")
        if not obj:
            continue
        if not obj.endswith(("?", ".", "!")):
            obj += "."
        obj = obj[:1].upper() + obj[1:]
        found.append((m.start() + lead, cut or m.end(), obj, c.group("cue").lower()))
    return found


def all_objections(text: str) -> list[tuple[int, int, str, str]]:
    quoted = find_objections(text)
    extra = [u for u in find_unquoted_objections(text)
             if not any(q[0] < u[1] and u[0] < q[1] for q in quoted)]
    return sorted(quoted + extra)


def first_words(text: str, limit: int) -> str:
    out: list[str] = []
    for sent in re.split(r"(?<=[.?!”])\s+", text):
        w = sent.split()
        if out and len(out) + len(w) > limit:
            break
        out += w
    return " ".join(out[:limit])


def is_eval(t: Turn) -> bool:
    m = re.match(r"Book [IV]+, Chapter ([IVXLC]+):", t.section)
    return bool(m) and roman_to_int(m.group(1)) % EVAL_CHAPTER_EVERY == 0


def answer_after(work_turns: list[Turn], i: int, start: int, stop: int | None,
                 min_words: int, max_words: int) -> str:
    t = work_turns[i]
    reply = t.text[start:stop].strip().lstrip(";:,—- ")
    k = i + 1
    while (stop is None and len(reply.split()) < min_words and k < len(work_turns)
           and work_turns[k].section == t.section):
        nxt = work_turns[k].text
        later = all_objections(nxt)
        reply = norm(reply + " " + (nxt[:later[0][0]] if later else nxt))
        if later:
            break
        k += 1
    reply = first_words(reply, max_words)
    return reply[:1].upper() + reply[1:]


def build_sft(turns: list[Turn], min_words: int = 15, max_words: int = 200,
              min_objection_words: int = 3, with_topic_prompts: bool = False) -> list[dict]:
    """Objection/reply examples, plus optional essay-topic examples."""
    examples = []
    by_work: dict[str, list[Turn]] = {}
    for t in turns:
        by_work.setdefault(t.work_id, []).append(t)
    for work_turns in by_work.values():
        for i, t in enumerate(work_turns):
            objs = all_objections(t.text)
            for j, (start, end, obj, cue) in enumerate(objs):
                if len(obj.split()) < min_objection_words:
                    continue
                stop = objs[j + 1][0] if j + 1 < len(objs) else None
                reply = answer_after(work_turns, i, start=end, stop=stop,
                                     min_words=min_words, max_words=max_words)
                if len(reply.split()) < min_words:
                    continue
                examples.append(_example(t, f"Reader: {obj}", reply, "objection", "tagged"))
    if with_topic_prompts:
        examples.extend(_topic_examples(by_work.get("essays", []), min_words, max_words))
    return examples


def _topic_examples(turns: list[Turn], min_words: int, max_words: int) -> list[dict]:
    """One example per essay: a templated request built from the chapter
    title, answered by the opening of the essay. The user turn is written by
    us, hence attribution "synthetic_prompt"."""
    out, seen = [], set()
    for t in turns:
        if t.section in seen:
            continue
        seen.add(t.section)
        m = re.match(r"Book [IV]+, Chapter [IVXLC]+: (.+)$", t.section)
        if not m:
            continue
        reply = first_words(t.text, max_words)
        if len(reply.split()) >= min_words:
            out.append(_example(t, f"Reader: Tell me what you think on this subject: {m.group(1)}.",
                                reply, "essay_topic", "synthetic_prompt"))
    return out


def _example(t: Turn, user: str, reply: str, source: str, attribution: str) -> dict:
    return {
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": user},
                     {"role": "assistant", "content": reply}],
        "meta": {"work": t.work, "work_id": t.work_id, "section": t.section,
                 "turn_idx": t.idx, "attribution": attribution, "source": source,
                 "is_question": reply.rstrip().endswith("?"),
                 "sensitive": [*flag_sensitive(user + " " + reply, where(t.work_id, t.section)),
                               *(["suicide_context"] if "suicide_context" in t.sensitive else [])],
                 "split": "eval" if is_eval(t) else "train",
                 "source_url": t.source_url},
    }


# --------------------------------------------------------------------------
# RAG passages
# --------------------------------------------------------------------------


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
            # Montaigne's sentences run long: cut at a semicolon or colon
            # near the limit before falling back to a plain word cut
            cut = next((k + 1 for k in range(limit - 1, limit // 2, -1)
                        if w[k].endswith((";", ":"))), limit)
            pieces.append(" ".join(w[:cut]))
            w = w[cut:]
        cur += w
    if cur:
        pieces.append(" ".join(cur))
    return pieces


def build_passages(turns: list[Turn], target_words: int) -> list[dict]:
    """Group paragraphs into passages of at most `target_words` words.
    Passages never cross a chapter or letter, so `section` is always exact.
    Long paragraphs are split at sentence ends, so every passage fits the
    embedding model's input (all-MiniLM-L6-v2 reads ~256 tokens)."""
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
                lines.append(piece)
        text = "\n".join(lines)
        f = buf[0][0]
        pid, n = None, 0
        while pid is None or pid in used:     # identical text twice in a work: rehash
            salt = f"\0{n}" if n else ""
            pid = f"{f.work_id}-{hashlib.sha256((text + salt).encode('utf-8')).hexdigest()[:8]}"
            n += 1
        used.add(pid)
        passages.append({
            "id": pid, "work_id": f.work_id,
            "author": f.author, "work": f.work, "translator": f.translator,
            "section": f.section, "turn_range": [f.idx, buf[-1][0].idx],
            "speakers": [PERSONA],
            "montaigne_words": sum(len(p.split()) for _, p in buf),
            "speaker_uncertain": False,
            "addressee": f.addressee,
            "sensitive": flag_sensitive(text, where(f.work_id, f.section)),
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


def write_caution_csv(path: Path, passages: list[dict]) -> int:
    """Passages flagged `suicide`, as a starting list for the persona
    config's tier-2 caution list (keyed by chunk_id)."""
    import csv
    rows = [p for p in passages if "suicide" in p["sensitive"]]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["chunk_id", "section", "flags", "excerpt"])
        for p in rows:
            m = re.search(SENSITIVE_PATTERNS["suicide"], p["text"], re.I)
            a = max(0, (m.start() if m else 0) - 120)
            w.writerow([f"montaigne-{p['id']}", p["section"], " ".join(p["sensitive"]),
                        norm(p["text"][a:a + 300])])
    return len(rows)


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
    ap.add_argument("--out", type=Path, default=Path("data/processed/montaigne"))
    ap.add_argument("--raw", type=Path, default=Path("data/raw/montaigne"),
                    help="download cache (git-ignored)")
    ap.add_argument("--no-letters", action="store_true", help="Essays only, without the 16 letters")
    ap.add_argument("--min-words", type=int, default=15, help="min words for a Montaigne SFT reply")
    ap.add_argument("--max-words", type=int, default=200, help="max words for a Montaigne SFT reply")
    ap.add_argument("--with-topic-prompts", action="store_true",
                    help="add one templated 'Tell me what you think on <title>' example per essay")
    ap.add_argument("--passage-words", type=int, default=180,
                    help="max words per RAG passage (the embedding model reads ~256 tokens)")
    args = ap.parse_args(argv)

    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    page = fetch(raw_url(), args.raw / "3600-h.htm").decode("utf-8")
    clean_stats: dict = {}
    turns = parse_montaigne(page, clean_stats)
    if args.no_letters:
        turns = [t for t in turns if t.work_id != "letters"]

    passages = build_passages(turns, args.passage_words)
    context_sections = add_suicide_context(turns, passages)
    n_turns = write_jsonl(out / "turns.jsonl", (asdict(t) for t in turns))
    sft = build_sft(turns, args.min_words, args.max_words, with_topic_prompts=args.with_topic_prompts)
    n_sft = write_jsonl(out / "montaigne_sft.jsonl", sft)
    n_pass = write_jsonl(out / "rag_passages.jsonl", passages)
    n_caution = write_caution_csv(out / "caution_candidates.csv", passages)
    (out / "stats.json").write_text(json.dumps(
        {"source": {"repo": SOURCE["repo"], "commit": SOURCE["commit"], "path": SOURCE["path"],
                    "gutenberg_ebook": SOURCE["gutenberg_ebook"]},
         "turns": n_turns, "sft_examples": n_sft,
         "sft_split": {k: sum(e["meta"]["split"] == k for e in sft) for k in ("train", "eval")},
         "sft_source": {k: sum(e["meta"]["source"] == k for e in sft) for k in ("objection", "essay_topic")},
         "passages": n_pass,
         "passage_flags": {k: sum(k in p["sensitive"] for p in passages)
                           for k in [*SENSITIVE_PATTERNS, "suicide_context"]},
         "suicide_context_sections": sorted(context_sections),
         "caution_candidates": n_caution,
         "cleaning": clean_stats,
         "works": summarize(turns)},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"turns={n_turns} sft={n_sft} passages={n_pass} -> {out}")
    return 0


def summarize(turns: list[Turn]) -> dict:
    report: dict[str, dict] = {}
    for t in turns:
        r = report.setdefault(t.work_id, {"work": t.work, "translator": t.translator,
                                          "sections": set(), "paragraphs": 0, "montaigne_words": 0})
        r["sections"].add(t.section)
        r["paragraphs"] += 1
        r["montaigne_words"] += t.words
    for r in report.values():
        r["sections"] = len(r["sections"])
    return report


if __name__ == "__main__":
    sys.exit(main())
