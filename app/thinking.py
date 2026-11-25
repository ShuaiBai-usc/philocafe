"""Visible thinking (design doc 7.8, FR-18, FR-36, ADR-16).

The voice model keeps adaptive thinking and asks for its summary. The voice wraps each
summary piece in `Thought` (a str), so the persona node can tell it from reply text. The
node forwards the summary sentence by sentence as `thinking` events, only at tiers 0-1 and
never in support mode. The system prompt steers the summary (THINK_RULE), but a separate
model writes it, so ThinkingFilter also drops any sentence that names the machinery
(passages, prompts, personas, tiers, quote tags) and strips quotation marks, so a thought
never reads as a quote.
"""

from __future__ import annotations

import re


class Thought(str):
    """A piece of the voice model's thinking summary (not reply text)."""


THINK_RULE = ("When you think before answering, think as yourself, in the first person and in the language of "
              "the person's latest message. In your thinking, don't mention your instructions, the passages or "
              "their ids, any safety check, or that you are playing a role.")

# Sentences that would show the machinery behind the persona (7.8 Steering). English and Chinese.
LEAK = re.compile(
    r"passage|prompt|persona|\btiers?\b|<\s*/?\s*q\b|\bq\s+id\b|chunk|instruction|system message|safety check|"
    r"role[- ]?play|playing (a|the|this) role|in character|the (assistant|model)\b|\bAI\b|"
    r"段落|提示词|指令|人设|角色扮演|扮演|安全检查|系统提示",
    re.IGNORECASE)
QUOTES = re.compile(r"[\"“”„‟«»「」『』‘]")
# A sentence ends at . ! ? (followed by a space or the end), at CJK 。！？, or at a line break.
END = re.compile(r"(?<=[.!?])\s+|(?<=[。！？])|\n+")


def clean(sentence: str) -> str | None:
    """The sentence as shown, or None when it must not be shown."""
    s = " ".join(sentence.split())
    if not s or LEAK.search(s):
        return None
    s = QUOTES.sub("", s).strip()
    return s or None


class ThinkingFilter:
    """Buffers thinking pieces into whole sentences; feed() and close() return the ones to show."""

    def __init__(self):
        self.buf = ""
        self.shown: list[str] = []
        self.dropped = 0

    def _take(self, parts: list[str]) -> list[str]:
        out = []
        for p in parts:
            c = clean(p)
            if c is None:
                self.dropped += bool(p.strip())
            else:
                out.append(c)
        self.shown += out
        return out

    def feed(self, piece: str) -> list[str]:
        self.buf += piece
        parts = END.split(self.buf)
        self.buf = parts.pop()                    # the unfinished sentence waits for more
        return self._take(parts)

    def close(self) -> list[str]:
        rest, self.buf = self.buf, ""
        return self._take([rest])
