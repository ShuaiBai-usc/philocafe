#!/usr/bin/env python3
"""Philocafe · Seneca corpus pipeline.

Downloads public-domain English translations of Seneca's prose, strips
everything that is not Seneca's text (translator introductions, appendices,
endnotes, footnote markers, salutations and "Farewell" lines), splits the
works into paragraphs, and writes the same three JSONL files as the Socrates
pipeline (docs/socrates.md), so build_sqlite.py and retrieval.py work as is:

  turns.jsonl        one record per paragraph ("turn"), all works
  seneca_sft.jsonl   chat-format examples where Seneca is the assistant
  rag_passages.jsonl passages of at most ~180 words with citations, for retrieval

Seneca wrote letters and essays, not dialogues, so a "turn" is one paragraph
in Seneca's voice, and SFT examples come from the objections he puts in the
mouth of an imagined interlocutor ("'But,' you say, '...'") and his answer to
them. See docs/seneca.md for the reasoning and for copyright notes.

Sources (Standard Ebooks, pinned commits; markup is CC0):
  * Moral Letters to Lucilius, tr. Richard M. Gummere (Loeb, 1917-1925)
  * Dialogues (12 essays incl. On Anger, On the Shortness of Life, On Benefits,
    On Clemency and the three Consolations), tr. Aubrey Stewart (1887-1898)

Only the Python standard library is used. Run from the repository root:

    python3 scripts/seneca_pipeline.py
    python3 scripts/seneca_pipeline.py --with-topic-prompts
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

# Pinned to commits so that upstream proofreading changes cannot silently
# change the output. The commits are also recorded in stats.json.
SOURCES = {
    "letters": dict(
        repo="standardebooks/seneca_moral-letters-to-lucilius_richard-m-gummere",
        commit="f5bc9a761005af19c4948d1611bfa2e607443b20",
        translator="Richard M. Gummere"),
    "dialogues": dict(
        repo="standardebooks/seneca_dialogues_aubrey-stewart",
        commit="b950b7cb47d81377ab7d66ce7a14fbb9e1d11f5c",
        translator="Aubrey Stewart"),
}


def raw_url(src: str, name: str) -> str:
    s = SOURCES[src]
    return f"https://raw.githubusercontent.com/{s['repo']}/{s['commit']}/src/epub/text/{name}"


def read_url(src: str, name: str) -> str:
    # Citation link shown to users: the same pinned file served by jsDelivr,
    # which sends it as XHTML so the browser renders the text.
    s = SOURCES[src]
    return f"https://cdn.jsdelivr.net/gh/{s['repo']}@{s['commit']}/src/epub/text/{name}"


N_LETTERS = 124

# Essays in the Dialogues volume: file stem -> (work id, addressee).
# Work ids have no hyphen, so chunk_id "seneca-<work>-<8hex>" splits cleanly.
DIALOGUES = {
    "on-providence":                      ("providence", "Lucilius"),
    "on-the-firmness-of-the-wise-person": ("firmness", "Serenus"),
    "on-anger":                           ("anger", "Novatus"),
    "to-marcia-on-consolation":           ("marcia", "Marcia"),
    "on-a-happy-life":                    ("happy_life", "Gallio"),
    "on-leisure":                         ("leisure", "Serenus"),
    "on-peace-of-mind":                   ("peace_of_mind", "Serenus"),
    "on-the-shortness-of-life":           ("shortness_of_life", "Paulinus"),
    "to-polybius-on-consolation":         ("polybius", "Polybius"),
    "to-helvia-on-consolation":           ("helvia", "Helvia"),
    "on-clemency":                        ("clemency", "Nero"),
    "on-benefits":                        ("benefits", "Aebutius Liberalis"),
}

PERSONA = "Seneca"

SYSTEM_PROMPT = (
    "You are Seneca, the Roman Stoic, writing to a friend. You do not lecture "
    "from above: you admit your own faults, reason from everyday examples, "
    "answer objections honestly, and keep turning the person back to what is "
    "within their own power: their judgements, their use of time, their "
    "character."
)

# Passages touching on these themes are flagged so they can be reviewed and
# handled with care. Seneca defends rational suicide in several letters (24,
# 58, 70, 77, 78) and in On Providence 6 and To Marcia 20, so the suicide
# pattern also matches his own metaphors ("slip the cable", "the door is
# open", "open one's veins"). Flags are hints for corpus analysis, not a
# filter; retrieval does not use them (design doc v0.2, section 7.1).
_POSS = r"(his|her|their|one's|one’s|my|your|our)"
SENSITIVE_PATTERNS = {
    "suicide": (
        r"\b(suicide|self-destruction|self-murder"
        rf"|(take|took|taking|takes|end|ended|ending|ends) {_POSS} (own )?life"
        r"|(kill|kills|killed|killing|slay|slew|slain) (him|her|my|your|them|one|our)sel(f|ves)"
        r"|(lay|lays|laid|laying) violent hands (up)?on (him|her|them|my|your|one|our)sel(f|ves)"
        r"|violent hands (up)?on their own persons"
        rf"|(open|opens|opened|opening) {_POSS} veins|cut {_POSS} veins"
        rf"|(die|dies|died|perish|perished|fell) by {_POSS} own hands?"
        r"|slip the cable|(door|way out|road to freedom)s? (is|lies|stands) open"
        r"|(depart|departs|departed|departure|withdraw|withdrawal) from life"
        r"|(leave|leaves|left|leaving|quit|quits|quitting) life"
        r"|starv(e|ed|es|ing) (him|her|them|your|my|one)sel(f|ves)"
        rf"|(choose|chose|chooses|choosing) {_POSS} (own )?(death|end)"
        rf"|violence to {_POSS} own (life|person)|means of {_POSS} own destruction"
        r"|(path|paths|way|road|roads|door|doors) to freedom|burst the bonds"
        r"|(easy|easiest|open) (exit|way out)|(liberate|free) (him|her|your|my|one|them)sel(f|ves) from life"
        r"|die at (his|her|their|one's|one’s) own (time|command|wish|choosing)"
        r"|(sank|plunged|thrust|drove) [^.;]{0,40}into (his|her|their) own (throat|breast|body|heart)"
        r"|(abstain|abstained|abstaining) from (food|nourishment)|starv(e|ed|ing) to death"
        rf"|make an end of (life|{_POSS} (own )?life|(him|her|your|my|one|them)sel(f|ves))"
        r"|courage to die|desire to die|wish(es|ed)? to die|longing for death"
        r"|pierce your heart|lancet will open)\b"),
    "death": r"\b(death|dying|die|dies|died|corpse|hemlock|poison(ed)?|executed?|execution|funeral)\b",
    "violence": r"\b(murder(ed|er|s)?|slay|slain|slaughter(ed)?|beat(en)?|scourg(e|ed|ing)|tortur(e|ed|es)|crucif\w*|the rack)\b",
    # The three Consolations are addressed to bereaved people; grief content
    # matters for emotionally vulnerable users.
    "grief": r"\b(grief|griefs|griev(e|es|ed|ing)|mourn(s|ed|ing)?|bereave(d|ment))\b",
    "sexuality": r"\b(lovers?|sexual|intercourse|adulter(y|er|ers|ess)|lust)\b",
}

# SFT examples held out as an eval split. The Letters are one work, so they
# are split by letter (every tenth letter); three short essays are held out
# whole. Neighbouring examples share context, so we never split mid-letter.
EVAL_WORKS = ("providence", "leisure", "helvia")
EVAL_LETTER_EVERY = 10

XHTML = "{http://www.w3.org/1999/xhtml}"
EPUB_TYPE = "{http://www.idpf.org/2007/ops}type"

# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------


@dataclass
class Turn:
    # Same fields as the Socrates Turn, plus `addressee` and `sensitive`
    # (build_sqlite.py ignores keys it does not know).
    work_id: str
    work: str
    author: str
    translator: str
    source_url: str
    section: str          # "Letter LXX: On the Proper Time to Slip the Cable", "Book I, Chapter III"
    idx: int              # running paragraph index within the work
    speaker: str          # "Seneca"; "Serenus" for On Peace of Mind, chapter I
    kind: str             # speech (Seneca's own prose is speech, not narration)
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


# Keys below are "<work_id>|<section prefix>".
#
# Whole letters on suicide: the regex misses many of their euphemisms ("the
# harbour", "take his departure"), so every passage in them gets the flag.
SECTION_FLAGS = {
    "letters|Letter LXX:": ["suicide"],      # On the Proper Time to Slip the Cable
    "letters|Letter LXXVII:": ["suicide"],   # On Taking One's Own Life
}

# Sections that discuss suicide somewhere, read by hand, in addition to every
# section where the suicide pattern matches at least once. All passages in
# these sections get "suicide_context": a passage that praises death as
# freedom ("not to be born is the happiest lot") is risky next to one that
# names the act, even when it does not match the pattern itself.
SUICIDE_CONTEXT_SECTIONS = (
    "letters|Letter XXIV:",                  # Cato; "even when reason advises us to make an end of it"
    "marcia|Chapter XX",                     # death as the way out of slavery
    "marcia|Chapter XXII",                   # Cremutius Cordus starves himself
    "anger|Book III, Chapter XV",            # "the way to freedom": any vein in your body
)


def where(work_id: str, section: str) -> str:
    return f"{work_id}|{section}"


def in_sections(at: str, keys) -> bool:
    """A letter key ("letters|Letter LXX:") matches by prefix, since the
    section also holds the title; a chapter key must match exactly, so that
    "Chapter XX" does not match "Chapter XXII"."""
    return any(at == k or (k.endswith(":") and at.startswith(k)) for k in keys)


def flag_sensitive(text: str, at: str = "") -> list[str]:
    extra = [f for key, fs in SECTION_FLAGS.items() if in_sections(at, [key]) for f in fs]
    return [k for k, pat in SENSITIVE_PATTERNS.items()
            if k in extra or re.search(pat, text, re.I)]


def add_suicide_context(turns: list["Turn"], passages: list[dict]) -> set[str]:
    """Flag every turn and passage in a section that discusses suicide."""
    hit = {where(p["work_id"], p["section"]) for p in passages if "suicide" in p["sensitive"]}
    hit |= {where(t.work_id, t.section) for t in turns
            if in_sections(where(t.work_id, t.section), SUICIDE_CONTEXT_SECTIONS)}
    for t in turns:
        if where(t.work_id, t.section) in hit and "suicide_context" not in t.sensitive:
            t.sensitive.append("suicide_context")
    for p in passages:
        if where(p["work_id"], p["section"]) in hit and "suicide_context" not in p["sensitive"]:
            p["sensitive"].append("suicide_context")
    return hit


def roman_to_int(s: str) -> int:
    vals = dict(I=1, V=5, X=10, L=50, C=100)
    n = 0
    for a, b in zip(s, s[1:] + " "):
        v = vals[a]
        n += -v if vals.get(b, 0) > v else v
    return n


# --------------------------------------------------------------------------
# Parsing (Standard Ebooks XHTML)
# --------------------------------------------------------------------------

# Paragraph roles that are not Seneca's prose.
SKIP_P = ("z3998:salutation", "z3998:valediction", "se:bridgehead", "title")


def iter_paragraphs(section: ET.Element, path: tuple[str, ...] = ()):
    """Yield (path, speaker_hint, text, continues) for each prose paragraph.

    `path` is the chain of headings above the paragraph, e.g. ("Book I", "II").
    `continues` is True for verse quotations and "continued" paragraphs, which
    belong to the paragraph before them. `speaker_hint` is the chapter title
    in parentheses, e.g. "(Serenus)" in On Peace of Mind.
    """
    hint = None
    for el in section:
        tag = el.tag.replace(XHTML, "")
        et = el.get(EPUB_TYPE, "")
        if tag in ("h2", "h3", "h4", "h5"):
            path = path + (el_text(el),)
            continue
        if tag in ("hgroup", "header"):
            for h in el:
                htag = h.tag.replace(XHTML, "")
                if htag in ("h2", "h3", "h4", "h5"):
                    path = path + (el_text(h),)
                elif htag == "p" and h.get(EPUB_TYPE, "") == "title":
                    m = re.fullmatch(r"\((\w+)\)", el_text(h))
                    if m:
                        hint = m.group(1)
            continue
        if tag == "section":
            yield from iter_paragraphs(el, path)
            continue
        if tag == "blockquote":
            yield path, hint, el_text(el), True
            continue
        if tag == "p":
            if any(s in et for s in SKIP_P):
                continue
            yield path, hint, el_text(el), "continued" in (el.get("class") or "")


def letter_turns(n: int, xhtml: bytes) -> list[Turn]:
    root = ET.fromstring(xhtml)
    sec = next(s for s in root.iter(XHTML + "section") if s.get("id") == f"letter-{n}")
    title = norm("".join(root.find(f"{XHTML}head/{XHTML}title").itertext()))
    name = f"letter-{n}.xhtml"
    base = dict(work_id="letters", work="Moral Letters to Lucilius", author="Seneca",
                translator=SOURCES["letters"]["translator"],
                source_url=read_url("letters", name),
                speaker=PERSONA, kind="speech", attribution="explicit", addressee="Lucilius")
    return _collect(base, iter_paragraphs(sec), section_of=lambda path: title)


def dialogue_turns(stem: str, xhtml: bytes) -> list[Turn]:
    work_id, addressee = DIALOGUES[stem]
    root = ET.fromstring(xhtml)
    top = next(s for s in root.iter(XHTML + "section") if s.get("id") == stem)
    title = norm("".join(root.find(f"{XHTML}head/{XHTML}title").itertext()))
    base = dict(work_id=work_id, work=title, author="Seneca",
                translator=SOURCES["dialogues"]["translator"],
                source_url=read_url("dialogues", f"{stem}.xhtml"),
                speaker=PERSONA, kind="speech", attribution="explicit", addressee=addressee)

    def section_of(path):
        # path[0] is the work title; then "Book I" and a chapter numeral, or
        # just a chapter numeral.
        parts = [p for p in path[1:] if p]
        if len(parts) >= 2:
            return f"{parts[0]}, Chapter {parts[1]}"
        return f"Chapter {parts[0]}" if parts else ""

    return _collect(base, iter_paragraphs(top), section_of)


def _collect(base: dict, paras, section_of) -> list[Turn]:
    turns: list[Turn] = []
    for path, hint, text, continues in paras:
        if not text:
            continue
        section = section_of(path)
        if continues and turns and turns[-1].section == section:
            turns[-1].text = norm(turns[-1].text + " " + text)
            turns[-1].words = len(turns[-1].text.split())
            continue
        speaker = hint if hint else base["speaker"]
        turns.append(Turn(**{**base, "speaker": speaker}, section=section, idx=len(turns), text=text))
    for t in turns:
        t.sensitive = flag_sensitive(t.text, where(t.work_id, t.section))
    return turns


# --------------------------------------------------------------------------
# SFT: objection -> reply pairs
# --------------------------------------------------------------------------

# Cues that mark a quotation as an imagined interlocutor's objection, not a
# quotation of a poet or another philosopher ("says he" usually introduces
# Epicurus or Virgil, so it is not a cue).
YOU_CUE = r"you (say|ask|reply|object|retort|will say|will ask|will reply|may say|may ask|might say|exclaim|cry)"
OTHER_CUE = (r"(says|asks|cries|replies|objects) (our|my|the|an?) (adversary|opponent|objector|critic|antagonist)"
             r"|(says|asks|replies|objects) (one|another|some one|someone|somebody)"
             r"|(one|some one|someone|somebody) (may|might|will) (say|ask|object|reply)"
             r"|it (may|might|will) be (said|asked|objected|answered)")
CUE = rf"(?P<cue>{YOU_CUE}|{OTHER_CUE})"
QUOTE = re.compile(r"“([^“”]+)”")
CUE_AFTER = re.compile(rf"^,?\s*{CUE}\b(,? (perhaps|then|again|me))?[,.;:]?\s*", re.I)
CUE_BEFORE = re.compile(rf"\b{CUE}(,? (perhaps|then|again|me))?[,:]?\s*$", re.I)


def find_objections(text: str) -> list[tuple[int, int, str, str]]:
    """Return (start, end, objection, cue) for each cued quotation in text.

    Split quotations ("'But,' you say, 'why ...?'") are joined. `end` is the
    offset where Seneca's answer begins.
    """
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
            # the quotation continues right after the cue
            if i + 1 < len(quotes) and quotes[i + 1].start() == end:
                i += 1
                parts.append(quotes[i].group(1))
                end = quotes[i].end()
        # "'But,' you say, 'why ...?'" -> "But why ...?"
        obj = norm(" ".join(re.sub(r",$", "", p.strip()) for p in parts[:-1]) + " " + parts[-1].strip())
        obj = re.sub(r",$", ".", obj)
        obj = obj[:1].upper() + obj[1:]
        found.append((q.start(), end, obj, cue))
        i += 1
    return found


def first_words(text: str, limit: int) -> str:
    """Leading sentences of text, at most `limit` words (cut between words
    only when the first sentence alone is longer)."""
    out: list[str] = []
    for sent in re.split(r"(?<=[.?!”])\s+", text):
        w = sent.split()
        if out and len(out) + len(w) > limit:
            break
        out += w
    return " ".join(out[:limit])


def is_eval(t: Turn) -> bool:
    if t.work_id == "letters":
        m = re.match(r"Letter ([IVXLC]+)\b", t.section)
        return bool(m) and roman_to_int(m.group(1)) % EVAL_LETTER_EVERY == 0
    return t.work_id in EVAL_WORKS


def build_sft(turns: list[Turn], min_words: int = 15, max_words: int = 200,
              min_objection_words: int = 3, with_topic_prompts: bool = False,
              reported: list[dict] | None = None) -> list[dict]:
    """Objection/reply examples, plus reported-question examples (`reported`,
    from seneca_reported_prompts.json) and optional letter-topic examples.

    For every cued objection in a Seneca paragraph, the user turn is the
    objection and the assistant turn is Seneca's answer: the rest of the
    paragraph up to the next objection, extended into the following
    paragraphs of the same section when it is shorter than `min_words`,
    and cut at a sentence end to at most `max_words`.
    """
    examples = []
    by_work: dict[str, list[Turn]] = {}
    for t in turns:
        by_work.setdefault(t.work_id, []).append(t)
    for work_turns in by_work.values():
        for i, t in enumerate(work_turns):
            if t.speaker != PERSONA:
                continue
            objs = find_objections(t.text)
            for j, (start, end, obj, cue) in enumerate(objs):
                if len(obj.split()) < min_objection_words:
                    continue
                stop = objs[j + 1][0] if j + 1 < len(objs) else None
                reply = answer_after(work_turns, i, end, stop, min_words, max_words)
                if len(reply.split()) < min_words:
                    continue
                # In the letters "you" is Lucilius. In the essays "you" is often
                # a generic opponent (an Epicurean in On Benefits IV), not the
                # addressee, so it is not given a name.
                who = "Lucilius" if t.work_id == "letters" and cue.startswith("you") else "Interlocutor"
                examples.append(_example(t, f"{who}: {obj}", reply, "objection", "tagged"))
        if with_topic_prompts and work_turns[0].work_id == "letters":
            examples.extend(_topic_examples(work_turns, min_words, max_words))
    if reported:
        examples.extend(_reported_examples(by_work, reported, min_words, max_words))
    return examples


def answer_after(work_turns: list[Turn], i: int, start: int, stop: int | None,
                 min_words: int, max_words: int) -> str:
    """Seneca's answer starting at offset `start` of paragraph i: up to
    `stop` (the next objection) or the end of the paragraph, extended into
    the following paragraphs of the same section while it is shorter than
    `min_words`, and cut at a sentence end to at most `max_words`."""
    t = work_turns[i]
    reply = t.text[start:stop].strip().lstrip(";:,—- ")
    k = i + 1
    while (stop is None and len(reply.split()) < min_words and k < len(work_turns)
           and work_turns[k].section == t.section and work_turns[k].speaker == PERSONA):
        nxt = work_turns[k].text
        later = find_objections(nxt)
        reply = norm(reply + " " + (nxt[:later[0][0]] if later else nxt))
        if later:
            break
        k += 1
    reply = first_words(reply, max_words)
    return reply[:1].upper() + reply[1:]


def load_reported(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["prompts"] if path.exists() else []


def _reported_examples(by_work: dict[str, list[Turn]], prompts: list[dict],
                       min_words: int, max_words: int) -> list[dict]:
    """Examples from places where Seneca reports, without quotation marks,
    what Lucilius wrote or asked ("You complain that you have met with an
    ungrateful person."). The first-person user turn was rewritten by hand
    and is stored in seneca_reported_prompts.json with the exact source text
    (`anchor`), hence attribution "rewritten_report"."""
    out = []
    for pr in prompts:
        hit = None
        for i, t in enumerate(by_work.get(pr["work_id"], [])):
            at = where(t.work_id, t.section)
            if in_sections(at, [where(pr["work_id"], pr["section"])]) and pr["anchor"] in t.text:
                hit = i, t
                break
        if hit is None:
            print(f"[warn] reported prompt not found: {pr['work_id']} {pr['section']} "
                  f"{pr['anchor'][:40]!r}", file=sys.stderr)
            continue
        i, t = hit
        start = t.text.index(pr["anchor"]) + len(pr["anchor"])
        later = [o for o in find_objections(t.text) if o[0] >= start]
        reply = answer_after(by_work[pr["work_id"]], i, start, later[0][0] if later else None,
                             min_words, max_words)
        if len(reply.split()) < min_words:
            print(f"[warn] reported prompt has a short answer: {pr['anchor'][:40]!r}", file=sys.stderr)
            continue
        out.append(_example(t, pr["user"], reply, "reported", "rewritten_report"))
    return out


def _topic_examples(turns: list[Turn], min_words: int, max_words: int) -> list[dict]:
    """One example per letter: a templated request built from the letter's
    title, answered by the opening of the letter. The user turn is written by
    us, not by Seneca or Gummere, hence attribution "synthetic_prompt"."""
    out, seen = [], set()
    for t in turns:
        if t.section in seen or t.speaker != PERSONA:
            continue
        seen.add(t.section)
        m = re.match(r"Letter [IVXLC]+: (.+)$", t.section)
        if not m:
            continue
        reply = first_words(t.text, max_words)
        if len(reply.split()) >= min_words:
            # titles are in title case ("On Living to Oneself"), so they are
            # quoted as they are rather than lowercased into a sentence
            out.append(_example(t, f"Lucilius: Write to me on this subject: {m.group(1)}.",
                                reply, "letter_topic", "synthetic_prompt"))
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
            pieces.append(" ".join(w[:limit]))
            w = w[limit:]
        cur += w
    if cur:
        pieces.append(" ".join(cur))
    return pieces


def speaker_label(t: Turn) -> str:
    """Seneca's own prose carries no label; another voice (Serenus) does."""
    return "" if t.speaker == PERSONA else f"{t.speaker}: "


def build_passages(turns: list[Turn], target_words: int) -> list[dict]:
    """Group paragraphs into passages of at most `target_words` words.

    Passages never cross a letter or chapter, so `section` is always exact.
    Long paragraphs are split at sentence ends, so every passage fits the
    embedding model's input (all-MiniLM-L6-v2 reads ~256 tokens).
    """
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
        # Content-based id: stays the same when the corpus is rebuilt and
        # paragraph numbers shift; changes only when the passage text changes.
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
            "speakers": sorted({t.speaker for t, _ in buf}),
            "seneca_words": sum(len(p.split()) for t, p in buf if t.speaker == PERSONA),
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
    ap.add_argument("--out", type=Path, default=Path("data/processed/seneca"))
    ap.add_argument("--raw", type=Path, default=Path("data/raw/seneca"),
                    help="download cache (git-ignored)")
    ap.add_argument("--works", nargs="*",
                    help="work ids to include: letters and/or essay ids (default: all)")
    ap.add_argument("--min-words", type=int, default=15, help="min words for a Seneca SFT reply")
    ap.add_argument("--max-words", type=int, default=200, help="max words for a Seneca SFT reply")
    ap.add_argument("--with-topic-prompts", action="store_true",
                    help="add one templated 'Write to me on <title>' example per letter")
    ap.add_argument("--reported-prompts", type=Path,
                    default=Path(__file__).resolve().parent / "seneca_reported_prompts.json",
                    help="hand-rewritten user turns for reported questions")
    ap.add_argument("--no-reported", action="store_true",
                    help="leave out the reported-question examples")
    ap.add_argument("--passage-words", type=int, default=180,
                    help="max words per RAG passage (the embedding model reads ~256 tokens)")
    args = ap.parse_args(argv)

    out: Path = args.out
    raw_dir: Path = args.raw
    out.mkdir(parents=True, exist_ok=True)
    want = set(args.works or [])

    turns: list[Turn] = []
    if not want or "letters" in want:
        for n in range(1, N_LETTERS + 1):
            name = f"letter-{n}.xhtml"
            try:
                data = fetch(raw_url("letters", name), raw_dir / "letters" / name)
                lt = letter_turns(n, data)
            except Exception as e:  # noqa: BLE001
                print(f"[warn] letter {n}: {e}", file=sys.stderr)
                continue
            offset = sum(t.work_id == "letters" for t in turns)
            for t in lt:
                t.idx += offset          # running index across all letters
            turns.extend(lt)
    for stem, (wid, _) in DIALOGUES.items():
        if want and wid not in want:
            continue
        try:
            data = fetch(raw_url("dialogues", f"{stem}.xhtml"), raw_dir / "dialogues" / f"{stem}.xhtml")
            turns.extend(dialogue_turns(stem, data))
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {wid}: {e}", file=sys.stderr)

    passages = build_passages(turns, args.passage_words)
    context_sections = add_suicide_context(turns, passages)
    n_turns = write_jsonl(out / "turns.jsonl", (asdict(t) for t in turns))
    sft = build_sft(turns, args.min_words, args.max_words, with_topic_prompts=args.with_topic_prompts,
                    reported=[] if args.no_reported else load_reported(args.reported_prompts))
    n_sft = write_jsonl(out / "seneca_sft.jsonl", sft)
    n_pass = write_jsonl(out / "rag_passages.jsonl", passages)
    (out / "stats.json").write_text(json.dumps(
        {"source": {k: {"standard_ebooks_repo": v["repo"], "standard_ebooks_commit": v["commit"]}
                    for k, v in SOURCES.items()},
         "turns": n_turns, "sft_examples": n_sft,
         "sft_split": {k: sum(e["meta"]["split"] == k for e in sft) for k in ("train", "eval")},
         "sft_source": {k: sum(e["meta"]["source"] == k for e in sft)
                        for k in ("objection", "reported", "letter_topic")},
         "passages": n_pass,
         "passage_flags": {k: sum(k in p["sensitive"] for p in passages)
                           for k in [*SENSITIVE_PATTERNS, "suicide_context"]},
         "suicide_context_sections": sorted(context_sections),
         "works": summarize(turns)},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"turns={n_turns} sft={n_sft} passages={n_pass} -> {out}")
    return 0


def summarize(turns: list[Turn]) -> dict:
    report: dict[str, dict] = {}
    for t in turns:
        r = report.setdefault(t.work_id, {"work": t.work, "translator": t.translator,
                                          "sections": set(), "paragraphs": 0,
                                          "seneca_words": 0, "total_words": 0})
        r["sections"].add(t.section)
        r["paragraphs"] += 1
        r["total_words"] += t.words
        r["seneca_words"] += t.words if t.speaker == PERSONA else 0
    for r in report.values():
        r["sections"] = len(r["sections"])
    return report


if __name__ == "__main__":
    sys.exit(main())
