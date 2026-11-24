"""ClaudeVoice: reply text as str, the thinking summary as Thought (design doc 7.8, ADR-16)."""

from types import SimpleNamespace as NS

from langchain_core.messages import HumanMessage

from app.thinking import Thought
from app.voice import ClaudeVoice


def delta(kind, **kw):
    return NS(type="content_block_delta", delta=NS(type=kind, **kw))


class FakeStream:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self.events)

    def get_final_message(self):
        return NS(stop_reason="end_turn")


class FakeClient:
    def __init__(self, events):
        self.kwargs = None
        self.messages = NS(stream=self._stream)
        self._events = events

    def _stream(self, **kwargs):
        self.kwargs = kwargs
        return FakeStream(self._events)


def test_thinking_summary_comes_out_as_thoughts_and_text_as_str():
    client = FakeClient([NS(type="content_block_start"), delta("thinking_delta", thinking="Behind whom? "),
                         delta("signature_delta", signature="x"), delta("text_delta", text="Tell me.")])
    out = list(ClaudeVoice("claude-sonnet-5-5", client=client)("system", [HumanMessage("hi")]))
    assert out == ["Behind whom? ", "Tell me."]
    assert isinstance(out[0], Thought) and not isinstance(out[1], Thought)
    assert client.kwargs["thinking"] == {"type": "adaptive", "display": "summarized"}
