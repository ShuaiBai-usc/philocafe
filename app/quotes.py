"""Quote check (FR-12, ADR-04), applied while the reply streams.

The persona writes each quote as <q id="CHUNK_ID">exact words</q>. Plain text
streams straight through; a quote is held back until its closing tag arrives
and is then checked against the passages retrieved for this turn:

- found in the passage: shown in quotation marks, and its chunk is cited;
- not found, from a [speaker uncertain] line, too short, or never closed:
  shown without quotation marks, as a paraphrase, and recorded as a failure.

So no quote reaches the user unchecked. In a reply that isn't in English the
persona writes <q id="CHUNK_ID" src="exact English words">translation</q>:
the English in src is what gets checked, and the translation is what is shown.

After the reply, untagged text in double quotes is checked too and recorded
for the traceability metric (NFR-05); it has already been shown, so it is not
changed.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal, TypedDict, Union

from app.retrieval import Chunk

OPEN_TAG = re.compile(r'<q((?:\s+[a-z]+\s*=\s*"[^"]*")*)\s*>')
ATTRIBUTE = re.compile(r'([a-z]+)\s*=\s*"([^"]*)"')
CLOSE_TAG = "</q>"
MAX_TAG_LEN = 600          # an opening tag can carry a sentence of English in src
MIN_QUOTE_WORDS = 3
UNCERTAIN = "[speaker uncertain]"
UNTAGGED = re.compile(r'["“]([^"“”]{12,}?)["”]')


class QuoteCheck(TypedDict):
    chunk_id: str | None
    text: str                  # the words checked against the passage (src for a translated quote)
    translation: str | None    # what was shown instead, for a translated quote
    ok: bool
    reason: str   # verified | not_in_passages | speaker_uncertain | too_short | unclosed | untagged_found | untagged_not_found


# A citation carries the chunk plus "quote": the words that passed the check.
Output = Union[tuple[Literal["text"], str], tuple[Literal["citation"], dict]]


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[‘’`]", "'", text)
    text = re.sub(r"[“”]", '"', text)
    text = re.sub(r"[—–-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_marks(text: str) -> str:
    return text.strip().strip("\"'“”‘’").strip()


def _segments(quote: str) -> list[str]:
    """The pieces of a quote between ellipses, normalized, without edge punctuation."""
    parts = re.split(r"\.\.\.|…", quote)
    return [p for p in (normalize(part).strip(" .,;:!?\"'") for part in parts) if p]


def locate(quote: str, passage: str) -> Literal["found", "uncertain", "missing"]:
    segments = _segments(quote)
    if not segments:
        return "missing"
    lines = passage.split("\n")
    status = "found"
    for seg in segments:
        line = next((ln for ln in lines if seg in normalize(ln)), None)
        if line is not None:
            if line.startswith(UNCERTAIN):
                status = "uncertain"
        elif seg in normalize(passage):       # runs across lines
            if UNCERTAIN in passage:
                status = "uncertain"
        else:
            return "missing"
    return status


def _could_be_tag(buf: str) -> bool:
    """True while `buf` (starting with "<") may still turn into a quote tag."""
    if CLOSE_TAG.startswith(buf) or buf == "<":
        return True
    return buf.startswith("<q") and (len(buf) == 2 or buf[2] in " \t>") and ">" not in buf and len(buf) < MAX_TAG_LEN


class QuoteFilter:
    def __init__(self, chunks: Sequence[Chunk]):
        self.chunks = {c["chunk_id"]: c for c in chunks}
        self.checks: list[QuoteCheck] = []
        self.cited: list[str] = []
        self._buf = ""
        self._quote_id: str | None = None
        self._quote_src: str | None = None
        self._in_quote = False
        self._plain: list[str] = []     # text written outside quote tags, for the untagged scan

    def feed(self, delta: str) -> list[Output]:
        self._buf += delta
        return self._drain(final=False)

    def close(self) -> list[Output]:
        out = self._drain(final=True)
        self._scan_untagged()
        return out

    def _drain(self, final: bool) -> list[Output]:
        out: list[Output] = []
        while self._buf:
            if self._in_quote:
                end = self._buf.find(CLOSE_TAG)
                if end < 0:
                    if not final:
                        break
                    out += self._resolve(self._buf, closed=False)
                    self._buf = ""
                    break
                quote, self._buf = self._buf[:end], self._buf[end + len(CLOSE_TAG):]
                out += self._resolve(quote, closed=True)
                continue

            start = self._buf.find("<")
            if start < 0:
                self._text(out, self._buf)
                self._buf = ""
                break
            self._text(out, self._buf[:start])
            self._buf = self._buf[start:]
            if self._buf.startswith(CLOSE_TAG):          # stray closing tag
                self._buf = self._buf[len(CLOSE_TAG):]
                continue
            match = OPEN_TAG.match(self._buf)
            if match:
                attrs = dict(ATTRIBUTE.findall(match.group(1)))
                self._in_quote, self._quote_id, self._quote_src = True, attrs.get("id"), attrs.get("src")
                self._buf = self._buf[match.end():]
                continue
            if not final and _could_be_tag(self._buf):
                break                                    # wait for the rest of the tag
            self._text(out, "<")
            self._buf = self._buf[1:]
        return out

    def _text(self, out: list[Output], text: str) -> None:
        if text:
            out.append(("text", text))
            self._plain.append(text)

    def _resolve(self, raw: str, closed: bool) -> list[Output]:
        shown = _strip_marks(raw)
        claimed, src = self._quote_id, self._quote_src
        self._in_quote, self._quote_id, self._quote_src = False, None, None
        check = self._check(_strip_marks(src) if src else shown, claimed, closed)
        if src:
            check["translation"] = shown
        self.checks.append(check)
        if not check["ok"]:
            return [("text", shown)] if shown else []
        out: list[Output] = [("text", f"“{shown}”")]
        if check["chunk_id"] not in self.cited:
            self.cited.append(check["chunk_id"])
            out.append(("citation", {**self.chunks[check["chunk_id"]], "quote": check["text"]}))
        return out

    def _check(self, quote: str, claimed: str | None, closed: bool) -> QuoteCheck:
        def result(chunk_id, ok, reason):
            return QuoteCheck(chunk_id=chunk_id, text=quote, translation=None, ok=ok, reason=reason)

        if not closed:
            return result(claimed, False, "unclosed")
        if len(normalize(quote).split()) < MIN_QUOTE_WORDS:
            return result(claimed, False, "too_short")
        # The claimed passage first, then the others: a right quote with a wrong id is re-attributed.
        order = ([claimed] if claimed in self.chunks else []) + [cid for cid in self.chunks if cid != claimed]
        uncertain_in = None
        for cid in order:
            status = locate(quote, self.chunks[cid]["text"])
            if status == "found":
                return result(cid, True, "verified")
            if status == "uncertain" and uncertain_in is None:
                uncertain_in = cid
        if uncertain_in:
            return result(uncertain_in, False, "speaker_uncertain")
        return result(claimed, False, "not_in_passages")

    def _scan_untagged(self) -> None:
        plain = "".join(self._plain)
        for match in UNTAGGED.finditer(plain):
            text = match.group(1).strip()
            if len(text.split()) < 5:
                continue
            found = next((cid for cid, c in self.chunks.items() if locate(text, c["text"]) == "found"), None)
            self.checks.append(QuoteCheck(chunk_id=found, text=text, translation=None, ok=found is not None,
                                          reason="untagged_found" if found else "untagged_not_found"))


LEADING_TAG = re.compile(r"\s*<([A-Za-z_]+)[^>]*>")


class LeadingNotesFilter:
    """Drops a block of notes the voice model occasionally writes before its
    reply, such as <reasoning>…</reasoning>. Only a block at the very start is
    dropped, and if it never closes the text is let through rather than lost.
    """

    def __init__(self, limit: int = 4000):
        self.limit = limit
        self.dropped = False
        self._buf = ""
        self._state = "start"      # start -> hiding -> trim (blank lines after the block) -> pass
        self._name = ""

    def feed(self, delta: str) -> str:
        if self._state == "pass":
            return delta
        if self._state == "trim":
            delta = delta.lstrip()
            if delta:
                self._state = "pass"
            return delta
        self._buf += delta
        if self._state == "start":
            head = self._buf.lstrip()
            if not head:
                return ""
            match = LEADING_TAG.match(self._buf)
            if match and match.group(1).lower() != "q":
                self._state, self._name = "hiding", match.group(1)
            elif head.startswith("<") and not match and ">" not in head and len(head) < 200:
                return ""                                  # a tag may still be arriving
            else:
                return self._release()
        close = re.search(rf"</{re.escape(self._name)}\w*\s*>", self._buf)
        if close:
            self.dropped = True
            rest, self._buf = self._buf[close.end():].lstrip(), ""
            self._state = "pass" if rest else "trim"
            return rest
        return self._release() if len(self._buf) > self.limit else ""

    def close(self) -> str:
        return self._release() if self._state in ("start", "hiding") else ""

    def _release(self) -> str:
        out, self._buf, self._state = self._buf, "", "pass"
        return out
