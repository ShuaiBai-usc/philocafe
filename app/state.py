"""Graph state and the safety decision (design doc 9.1 and 7.3)."""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from app.mood import PersonaMood
from app.quotes import QuoteCheck
from app.retrieval import Chunk


class SafetyDecision(TypedDict):
    tier: int                     # 0-3, see design doc section 8
    tier_probs: dict[int, float]  # probability per tier
    needs_retrieval: bool
    route: str | None             # persona id; final milestone
    source: Literal["jev", "fallback"]
    model_version: str


class NodeTiming(TypedDict):
    name: str
    ms: float


class TurnState(TypedDict, total=False):
    thread_id: str
    persona_id: str
    messages: Annotated[list[AnyMessage], add_messages]
    mode: Literal["persona", "support"]
    return_request: bool          # this turn is the "ready to come back" button (FR-32)
    safety: SafetyDecision        # 7.3
    retrieved: list[Chunk]        # 7.1
    reply: str
    citations: list[str]          # chunk_ids actually quoted
    quotes: list[QuoteCheck]      # every quote checked this turn (FR-12, NFR-05)
    retrieval_query: str          # what was searched, translated into English if needed
    prefs: dict[str, int]         # this visitor's reply preferences (7.9); persona prompt only (FR-37)
    trace: list[NodeTiming]       # node name + ms, for the debug panel
    mood: PersonaMood             # 7.5: smoothed, carried across turns
    mood_candidate: str | None    # a new label waiting for its second turn (7.5 smoothing)
    suggestions: list[str]        # 7.9: what the user might say next, shown under this turn's reply
    thinking: list[str]           # 7.8: the thinking sentences shown this turn (logged by the eval, NFR-14)
