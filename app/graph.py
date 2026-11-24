"""The turn graph (design doc 9.1): START -> safety -> (exit | moderator -> persona) -> END."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from functools import partial
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
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


class CannotRegenerate(Exception):
    """The latest reply is not a persona reply that can be generated again (7.9)."""


def rewind_last_turn(graph, thread_id: str) -> tuple[str, str]:
    """Regenerate (FR-41): drop the latest persona reply and the user message before it
    from the checkpoint, and return (text, persona_id) to run that turn again. Refused in
    support mode and when the latest reply is in the system voice (exit, support)."""
    config = {"configurable": {"thread_id": thread_id}}
    state = graph.get_state(config).values
    messages = state.get("messages") or []
    if state.get("mode") == "support":
        raise CannotRegenerate("The conversation is paused.")
    last = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    if last is None or last.name in (None, "system") or messages[-1] is not last:
        raise CannotRegenerate("There is no persona reply to generate again.")
    i = messages.index(last)
    asked = next((m for m in reversed(messages[:i]) if isinstance(m, HumanMessage)), None)
    if asked is None:
        raise CannotRegenerate("There is no message to answer again.")
    graph.update_state(config, {"messages": [RemoveMessage(id=asked.id), RemoveMessage(id=last.id)]},
                       as_node="persona")
    return asked.content, last.name


def run_turn(graph, thread_id: str, text: str, persona_id: str, intent: str | None = None,
             prefs: dict[str, int] | None = None, paused: bool | None = None) -> Iterator[Event]:
    """Run one user turn and yield its UI events, ending with `done` or `error`.
    `intent="return"` marks the web app's "ready to come back" button (FR-32).
    `prefs` are the visitor's reply preferences (7.9); only the persona node reads them.
    `paused` is the user's pause across all their conversations (7.10): when given, it sets
    whether this turn starts in support mode, whatever this thread's own checkpoint says."""
    config = {"configurable": {"thread_id": thread_id}}
    # Per-turn fields are reset here; messages and mode carry over in the checkpoint.
    # The message is tagged with the persona it is addressed to, so each persona gets its own history.
    turn = {"thread_id": thread_id, "persona_id": persona_id, "messages": [HumanMessage(text, name=persona_id)],
            "trace": [], "retrieved": [], "reply": "", "citations": [], "quotes": [], "retrieval_query": "",
            "return_request": intent == "return", "prefs": dict(prefs or {})}
    if paused is not None:
        turn["mode"] = "support" if paused else "persona"
    try:
        yield from graph.stream(turn, config, stream_mode="custom")
        state = graph.get_state(config).values
        yield event("trace", nodes=state["trace"],
                    retrieved=[c["chunk_id"] for c in state["retrieved"]],
                    skipped=skipped_quotes(state.get("quotes", [])))
        # The stored reply's id (7.10), so the UI can rate it or save it as a note.
        last = state["messages"][-1] if state.get("messages") else None
        yield event("done", **({"message_id": last.id} if isinstance(last, AIMessage) and last.name != "system" else {}))
    except Exception as e:
        yield event("error", code=type(e).__name__, message=str(e)[:500])
