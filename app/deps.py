"""External services the graph nodes call, passed in so tests can use fakes."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict

from langchain_core.messages import AnyMessage

from app.config import Config
from app.retrieval import Chunk


class SafetyScores(TypedDict):
    tier_probs: dict[int, float]
    needs_retrieval: bool
    model_version: str


class SafetyModel(Protocol):
    source: Literal["jev", "fallback"]

    def classify(self, history: Sequence[AnyMessage]) -> SafetyScores: ...


Retrieve = Callable[..., list[Chunk]]                              # design doc 7.1
Generate = Callable[[str, Sequence[AnyMessage]], Iterator[str]]    # system prompt, messages -> text deltas


@dataclass
class Deps:
    config: Config
    safety_models: Sequence[SafetyModel]   # tried in order: Jev, then the fallback
    retrieve: Retrieve
    generate: Generate
    resources: Sequence[dict] = ()         # crisis resources for the exit flow: {name, contact}


def default_deps() -> Deps:
    """Deps wired to the real services."""
    raise NotImplementedError("the Jev, fallback and voice clients land with the safety and persona steps; "
                              "use --fake until then")
