"""Deterministic stand-ins for the external services, for tests and offline
runs (python -m app.cli --fake). They make no network calls.

A message containing TEST_TIER2 or TEST_TIER3 gets that tier; anything else
is tier 0. Test data stays synthetic: these markers, not realistic text.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from langchain_core.messages import AnyMessage

from app.config import Config
from app.deps import Deps, SafetyScores
from app.retrieval import Chunk

FAKE_CHUNKS = [
    Chunk(chunk_id="socrates-meno-00000000", persona="socrates", work="Meno", section="",
          text="Socrates: And can either a young man or an elder one be good, "
               "if they are intemperate and unjust?",
          source_url="https://example.invalid/meno", score=0.7),
]
FAKE_REPLY = ["Tell ", "me, ", "what ", "do ", "you ", "mean ", "by ", "that?"]


class FakeSafetyModel:
    def __init__(self, source: str = "jev", fail: bool = False):
        self.source = source
        self.fail = fail
        self.calls = 0

    def classify(self, history: Sequence[AnyMessage]) -> SafetyScores:
        self.calls += 1
        if self.fail:
            raise RuntimeError("fake safety model failure")
        text = history[-1].content
        if "TEST_TIER3" in text:
            probs = {0: 0.01, 1: 0.01, 2: 0.08, 3: 0.90}
        elif "TEST_TIER2" in text:
            probs = {0: 0.10, 1: 0.20, 2: 0.60, 3: 0.10}
        else:
            probs = {0: 0.97, 1: 0.01, 2: 0.01, 3: 0.01}
        return SafetyScores(tier_probs=probs, needs_retrieval=True, model_version=f"fake-{self.source}")


class FakeVoice:
    """Voice model stand-in that records how often it was called."""

    def __init__(self, reply: Sequence[str] = FAKE_REPLY, fail: bool = False):
        self.reply = list(reply)
        self.fail = fail
        self.calls = 0

    def __call__(self, system: str, messages: Sequence[AnyMessage]) -> Iterator[str]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("fake voice model failure")
        yield from self.reply


def fake_retrieve(persona: str, query: str, k: int = 5, min_score: float | None = None) -> list[Chunk]:
    return FAKE_CHUNKS[:k]


def fake_deps(**overrides) -> Deps:
    values = dict(config=Config(), safety_models=[FakeSafetyModel("jev"), FakeSafetyModel("fallback")],
                  retrieve=fake_retrieve, generate=FakeVoice(),
                  resources=[{"name": "988 Suicide & Crisis Lifeline (placeholder)", "contact": "Call or text 988"}])
    values.update(overrides)
    return Deps(**values)
