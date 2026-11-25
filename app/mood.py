"""Persona mood (design doc 7.5, FR-15 to FR-17, FR-34, FR-66).

The voice model opens every reply with a tag, <mood label="curious" intensity="0.6"/>, naming
how the persona feels about the ideas in play. MoodTagFilter takes the tag off the stream
before anything reaches the user or the quote check; next_mood() smooths it across turns so
the portrait does not flicker. From tier 2 up, during an exit and in support mode the mood is
locked at attentive and the tag is ignored (FR-34); only the safety node's tier decides that.

No extra model call and no extra latency (ADR-12).
"""

from __future__ import annotations

import re
from typing import TypedDict


class PersonaMood(TypedDict):
    label: str          # one of the persona's moods
    intensity: float    # 0 to 1, smoothed across turns
    locked: bool        # True while FR-34 holds it at attentive


CALM = "attentive"                    # every persona's mood set includes it
FALLBACK = (CALM, 0.3)                # a missing, malformed or unknown tag
ALPHA = 0.5                           # moving average of the tagged intensity
STRONG = 0.8                          # a label this strong switches at once
LOCKED = PersonaMood(label=CALM, intensity=0.2, locked=True)
MAX_MOODS = 6

TAG = re.compile(r"<mood\b([^>]*?)/?>", re.IGNORECASE)
ATTR = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
OPENING = "<mood"

MOOD_RULE = ("Begin every reply with a mood tag, then a space, then your words: "
             '<mood label="LABEL" intensity="0.0-1.0"/>. LABEL is one of: {labels}. It is how you feel about '
             "the ideas in this exchange right now (how strongly, from 0 to 1), never a feeling about the person. "
             "Use attentive when nothing stands out. The tag is taken off before the person sees your reply.")


def mood_rule(moods: tuple[str, ...]) -> str:
    return MOOD_RULE.format(labels=", ".join(moods))


def parse_tag(attrs: str, allowed: tuple[str, ...]) -> tuple[str, float]:
    found = {k.lower(): v.strip() for k, v in ATTR.findall(attrs or "")}
    label = found.get("label", "").lower()
    try:
        intensity = float(found.get("intensity", ""))
    except ValueError:
        return FALLBACK
    if label not in allowed or not 0.0 <= intensity <= 1.0:
        return FALLBACK
    return label, intensity


class MoodTagFilter:
    """Takes a leading mood tag off a streamed reply. `tag` is None until the start of the
    reply is settled, then the (label, intensity) tagged, or FALLBACK when there was none."""

    def __init__(self, allowed: tuple[str, ...], limit: int = 300):
        self.allowed = allowed
        self.limit = limit
        self.tag: tuple[str, float] | None = None
        self._buf = ""

    @property
    def settled(self) -> bool:
        return self.tag is not None

    def feed(self, delta: str) -> str:
        if self.settled:
            return delta
        self._buf += delta
        head = self._buf.lstrip()
        if not head:
            return ""
        if head[:len(OPENING)].lower() == OPENING[:len(head)].lower() and len(head) < len(OPENING):
            return ""                                           # "<mo" may still become a tag
        if head[:len(OPENING)].lower() == OPENING:
            m = TAG.match(head)
            if m is None:
                return "" if ">" not in head and len(head) < self.limit else self._release(FALLBACK)
            self.tag = parse_tag(m.group(1), self.allowed)
            rest, self._buf = head[m.end():].lstrip(), ""
            return rest
        return self._release(FALLBACK)

    def close(self) -> str:
        return "" if self.settled else self._release(FALLBACK)

    def _release(self, tag: tuple[str, float]) -> str:
        self.tag = tag
        out, self._buf = self._buf.lstrip(), ""
        return out


def next_mood(prev: dict | None, candidate: str | None, label: str, intensity: float) -> tuple[PersonaMood, str | None]:
    """Smoothing (7.5): intensity is a moving average of the tagged values; the label changes
    only when the same new label is tagged two turns in a row, or once at STRONG or above.
    Returns the new mood and the label waiting for its second turn, if any."""
    if not prev or prev.get("locked"):
        return PersonaMood(label=label, intensity=round(intensity, 3), locked=False), None
    smoothed = round(ALPHA * intensity + (1 - ALPHA) * float(prev.get("intensity", intensity)), 3)
    if label == prev["label"]:
        return PersonaMood(label=label, intensity=smoothed, locked=False), None
    if intensity >= STRONG or candidate == label:
        return PersonaMood(label=label, intensity=smoothed, locked=False), None
    return PersonaMood(label=prev["label"], intensity=smoothed, locked=False), label
