"""Read aloud while the reply streams (design doc 7.6, FR-09).

The reply used to be read only once it was finished and stored, because the speech route reads
only text it can find in the thread's stored persona replies. To start speaking with the first
words, the server now marks pieces of the reply as it streams them: `speakable` events, each one
sentence or a few (`{text, sig}`), where `sig` is an HMAC over the thread id and the text, made
with the sign-in token key. The speech route reads a signed piece without looking it up, so it
still reads only what this server wrote for this conversation, and it still reads nothing in
support mode. Tokens reach the UI already quote-checked (persona.py), so nothing unchecked is read.

The first piece goes out at the first sentence end, or at a comma once it is long enough, so the
voice starts early; later pieces join short sentences so the requests stay few and full.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator

from app.events import Event

FIRST_MIN, NEXT_MIN, CLAUSE_MIN, MAX = 1, 40, 60, 560
# A sentence ends at . ! ? (then a space), at CJK 。！？, or at a line break; closing quotes stay with it.
END = re.compile(r"[.!?]+[\"”’)\]]*\s+|[。！？]+[\"”’)\]」』]*|\n+")
CLAUSE = re.compile(r"[,;:，；：]\s*")


def norm(text: str) -> str:
    return " ".join(text.split())


class Splitter:
    """Feeds streamed reply text; returns the pieces ready to be read aloud."""

    def __init__(self):
        self.buf = ""
        self.ready: list[str] = []      # whole sentences waiting to reach NEXT_MIN
        self.first = True

    def _out(self, piece: str) -> list[str]:
        piece = norm(piece)
        if not piece:
            return []
        self.first = False
        return [piece]

    def feed(self, text: str) -> list[str]:
        self.buf += text
        out: list[str] = []
        while (m := END.search(self.buf)):
            self.ready.append(self.buf[:m.end()])
            self.buf = self.buf[m.end():]
            joined = "".join(self.ready)
            if len(norm(joined)) >= (FIRST_MIN if self.first else NEXT_MIN):
                out += self._out(joined)
                self.ready = []
        if self.first and not self.ready and len(self.buf) >= CLAUSE_MIN and (c := list(CLAUSE.finditer(self.buf))):
            cut = c[-1].end()                   # no sentence end yet: start on the first clause
            out += self._out(self.buf[:cut])
            self.buf = self.buf[cut:]
        if len(self.buf) > MAX:                 # a very long sentence: read it in parts
            cut = self.buf.rfind(" ", 0, MAX) if " " in self.buf[:MAX] else MAX
            out += self._out("".join(self.ready) + self.buf[:cut])
            self.ready, self.buf = [], self.buf[cut:]
        return out

    def close(self) -> list[str]:
        rest = "".join(self.ready) + self.buf
        self.ready, self.buf = [], ""
        return self._out(rest)


def with_speakable(events: Iterable[Event], sign: Callable[[str], str]) -> Iterator[Event]:
    """The turn's events, plus `speakable` events for the persona's reply as it streams."""
    split, persona = Splitter(), False

    def pieces(texts):
        for t in texts:
            yield Event(type="speakable", data={"text": t, "sig": sign(t)})

    for e in events:
        kind = e["type"]
        if kind == "voice":
            persona, split = e["data"].get("speaker") == "persona", Splitter()
        if persona and kind in ("suggestions", "done", "error", "exit"):
            yield from pieces(split.close())
        yield e
        if persona and kind == "token":
            yield from pieces(split.feed(e["data"].get("text", "")))
    if persona:
        yield from pieces(split.close())
