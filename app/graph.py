"""The turn graph (design doc 9.1): START -> safety -> (exit | moderator -> persona) -> END."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from functools import partial
from typing import Literal

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.deps import Deps
from app.events import Event, event
from app.exit import exit_node
from app.moderator import moderator_node
from app.persona import persona_node
from app.safety.node import safety_node
from app.state import NodeTiming, TurnState


def timed(name: str, fn: Callable[[TurnState], dict]) -> Callable[[TurnState], dict]:
    """Wrap a node so its wall time is appended to the turn's trace."""
    def node(state: TurnState) -> dict:
        start = time.perf_counter()
        update = fn(state)
        ms = round((time.perf_counter() - start) * 1000, 1)
        return {**update, "trace": [*state.get("trace", []), NodeTiming(name=name, ms=ms)]}
    return node


def route_after_safety(state: TurnState) -> Literal["exit", "moderator"]:
    """Design doc 9.1: exit on tier 3, or in support mode unless the user asked for the
    persona back (safety's `route`) and risk has dropped to tier 1 or below (FR-32)."""
    safety = state["safety"]
    if safety["tier"] == 3:
        return "exit"
    if state.get("mode") == "support":
        return "moderator" if safety["route"] and safety["tier"] <= 1 else "exit"
    return "moderator"


def build_graph(deps: Deps, checkpointer=None):
    g = StateGraph(TurnState)
    g.add_node("safety", timed("safety", partial(safety_node, deps=deps)))
    g.add_node("moderator", timed("moderator", partial(moderator_node, deps=deps)))
    g.add_node("persona", timed("persona", partial(persona_node, deps=deps)))
    g.add_node("exit", timed("exit", partial(exit_node, deps=deps)))
    g.add_edge(START, "safety")
    g.add_conditional_edges("safety", route_after_safety, ["exit", "moderator"])
    g.add_edge("moderator", "persona")
    g.add_edge("persona", END)
    g.add_edge("exit", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())


def skipped_quotes(quotes) -> list[dict]:
    """Quotes the check refused, for the trace (7.2 `skipped`); untagged ones are only measured."""
    return [{"chunk_id": q["chunk_id"], "reason": q["reason"]}
            for q in quotes if not q["ok"] and not q["reason"].startswith("untagged")]


def run_turn(graph, thread_id: str, text: str, persona_id: str) -> Iterator[Event]:
    """Run one user turn and yield its UI events, ending with `done` or `error`."""
    config = {"configurable": {"thread_id": thread_id}}
    # Per-turn fields are reset here; messages and mode carry over in the checkpoint.
    turn = {"thread_id": thread_id, "persona_id": persona_id, "messages": [HumanMessage(text)],
            "trace": [], "retrieved": [], "reply": "", "citations": [], "quotes": [], "retrieval_query": ""}
    try:
        yield from graph.stream(turn, config, stream_mode="custom")
        state = graph.get_state(config).values
        yield event("trace", nodes=state["trace"],
                    retrieved=[c["chunk_id"] for c in state["retrieved"]],
                    skipped=skipped_quotes(state.get("quotes", [])))
        yield event("done")
    except Exception as e:
        yield event("error", code=type(e).__name__, message=str(e)[:500])
