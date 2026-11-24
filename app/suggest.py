"""Suggested next messages (design doc 7.9, FR-46): two or three things the user might say next,
shown under the latest reply as buttons; tapping one sends it as an ordinary message, so the
safety node checks it like anything typed.

The voice model writes them in the same call, after its reply, in a <next> block (one line
each, in the user's voice and language). NextFilter holds the block back from the stream, so
it never reaches the user's bubble, the quote check or read-aloud; parse() turns it into a
list. Nothing is suggested from tier 2 up (the persona node drops the block), and the exit
flow and support mode never suggest anything.
"""

from __future__ import annotations

import re

OPEN, CLOSE = "<next>", "</next>"
MAX_SUGGESTIONS = 3
MAX_CHARS = 80

NEXT_RULE = ("After your reply, on a new line, write <next>, then two or three short things the person might "
             "say to you next, each on its own line, then </next>. Write them as the person would, in their "
             "words and their language: a follow-up question, a doubt, or an example from their own life. "
             "Keep each under 12 words (under 25 characters in Chinese or Japanese), make them different from "
             "each other, and never put words about harming anyone in their mouth. The block is shown as "
             "buttons, not as part of your reply.")

BULLET = re.compile(r"^\s*(?:[-*•·]|\d+[.)、]|[(（]?\d+[)）])\s*")
QUOTES = "\"'“”‘’「」『』"


class NextFilter:
    """Passes the reply through and keeps everything from <next> on; `block` holds what it kept."""

    def __init__(self):
        self.block: str | None = None
        self._tail = ""

    def feed(self, delta: str) -> str:
        if self.block is not None:
            self.block += delta
            return ""
        text = self._tail + delta
        i = text.lower().find(OPEN)
        if i >= 0:
            self.block, self._tail = text[i + len(OPEN):], ""
            return text[:i].rstrip()
        # Hold back a tail that could still become "<next>", and the blank space before it.
        keep = next((k for k in range(min(len(OPEN) - 1, len(text)), 0, -1)
                     if OPEN.startswith(text[-k:].lower())), 0)
        head = text[:len(text) - keep]
        out = head.rstrip()
        self._tail = head[len(out):] + text[len(head):]
        return out

    def close(self) -> str:
        out, self._tail = self._tail, ""
        return out


def parse(block: str | None) -> list[str]:
    if not block:
        return []
    body = block.split(CLOSE, 1)[0]
    out: list[str] = []
    for line in body.splitlines():
        s = BULLET.sub("", line).strip().strip(QUOTES).strip()
        if s and len(s) <= MAX_CHARS and s.lower() not in (x.lower() for x in out) and "<" not in s:
            out.append(s)
    return out[:MAX_SUGGESTIONS]
