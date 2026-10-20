"""UI events (design doc 7.2).

Nodes emit events through LangGraph's stream writer; run_turn() yields them
to the UI. Streamlit and the final HTTP UI consume the same event types.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.config import get_stream_writer

EVENT_TYPES = ("voice", "token", "citation", "exit", "safety", "trace", "done", "error")


class Event(TypedDict):
    type: str
    data: dict[str, Any]


def event(type_: str, **data: Any) -> Event:
    if type_ not in EVENT_TYPES:
        raise ValueError(f"unknown event type: {type_!r}")
    return Event(type=type_, data=data)


def emit(type_: str, **data: Any) -> None:
    """Send an event to the UI from inside a graph node."""
    get_stream_writer()(event(type_, **data))
