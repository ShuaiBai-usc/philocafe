"""External services the graph nodes call, passed in so tests can use fakes."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol, TypedDict

from langchain_core.messages import AnyMessage

from app.config import Config, load_config
from app.personas import PersonaConfig, load_personas
from app.retrieval import Chunk
from app.safety.log import DecisionLog


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
    personas: Mapping[str, PersonaConfig]
    resources: Sequence[dict] = ()         # crisis resources for the exit flow: {name, contact}
    decision_log: DecisionLog = field(default_factory=DecisionLog)
    translate: Callable[[str], str] | None = None   # non-English query -> English, before retrieval


def default_deps(config: Config | None = None) -> Deps:
    """Deps wired to the real services. Opens the corpus database at once, so a
    missing database or sqlite-vec fails here rather than on the first turn."""
    from app import retrieval
    from app.exit import load_resources
    from app.safety.fallback import FallbackModel
    from app.safety.jev import JevModel
    from app.translate import ClaudeTranslator
    from app.voice import ClaudeVoice

    config = config or load_config()
    retrieval.open_db()
    return Deps(config=config,
                safety_models=[JevModel(config.safety), FallbackModel(config.safety)],
                retrieve=retrieval.retrieve,
                generate=ClaudeVoice(config.voice_model, effort=config.voice_effort),
                personas=load_personas(),
                resources=load_resources(),
                translate=ClaudeTranslator(config.translate_model, config.translate_timeout_s))
