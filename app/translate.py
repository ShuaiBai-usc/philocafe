"""Translate non-English questions into English before retrieval.

The corpus is Jowett's English and its embedding model and keyword index are
English-only, so a question written in Chinese (or any non-Latin script) finds
almost nothing. Only the search query is translated: the persona still reads
and answers the user's own words.
"""

from __future__ import annotations

import anthropic

from app.config import secret

LATIN_SHARE = 0.5
SYSTEM = ("Translate the user's text into English, to be used as a search query over Plato's dialogues. "
          "Reply with the translation only.")


def needs_translation(text: str) -> bool:
    """True when fewer than half the letters are ASCII (Chinese, Japanese, Russian, ...)."""
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(c.isascii() for c in letters) / len(letters) < LATIN_SHARE


class ClaudeTranslator:
    def __init__(self, model: str, timeout_s: float = 5.0, client: anthropic.Anthropic | None = None):
        self.model = model
        self.timeout_s = timeout_s
        self._client = client

    def _get_client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=secret("ANTHROPIC_API_KEY"), timeout=self.timeout_s,
                                               max_retries=1)
        return self._client

    def __call__(self, text: str) -> str:
        response = self._get_client().messages.create(
            model=self.model,
            max_tokens=300,
            system=SYSTEM,
            thinking={"type": "disabled"},
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": text}],
        )
        translation = "".join(b.text for b in response.content if b.type == "text").strip()
        if response.stop_reason != "end_turn" or not translation:
            raise RuntimeError(f"translation failed (stop_reason={response.stop_reason})")
        return translation
