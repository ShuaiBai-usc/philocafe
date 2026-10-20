"""Graph state and the safety decision (design doc 9.1 and 7.3)."""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

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
    safety: SafetyDecision        # 7.3
    retrieved: list[Chunk]        # 7.1
    reply: str
    citations: list[str]          # chunk_ids actually quoted
    trace: list[NodeTiming]       # node name + ms, for the debug panel
