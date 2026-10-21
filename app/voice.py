"""Voice model: streams the persona's reply from Claude.

The system prompt is marked for prompt caching, since it is the same on every
turn of a persona. A SystemMessage becomes a mid-conversation system message,
which the persona node uses for the turn's passages.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import anthropic
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage

from app.config import secret


class VoiceRefused(RuntimeError):
    """The voice model declined to answer (stop_reason "refusal")."""


def to_api_messages(messages: Sequence[AnyMessage]) -> list[dict]:
    def role(m):
        if isinstance(m, HumanMessage):
            return "user"
        return "system" if isinstance(m, SystemMessage) else "assistant"
    return [{"role": role(m), "content": m.content} for m in messages]


class ClaudeVoice:
    def __init__(self, model: str, client: anthropic.Anthropic | None = None, max_tokens: int = 2048,
                 effort: str = "low"):
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort
        self._client = client

    def _get_client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=secret("ANTHROPIC_API_KEY"))
        return self._client

    def __call__(self, system: str, messages: Sequence[AnyMessage]) -> Iterator[str]:
        with self._get_client().messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": self.effort},
            messages=to_api_messages(messages),
        ) as stream:
            yield from stream.text_stream
            final = stream.get_final_message()
        if final.stop_reason == "refusal":
            raise VoiceRefused(getattr(final.stop_details, "category", None) or "refusal")
