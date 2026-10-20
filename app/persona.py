"""Persona node (M-03). Skeleton: retrieves when the safety decision says so
and streams the voice model's reply. The persona config, prompt and quote
check replace this in the persona step."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from app.deps import Deps
from app.events import emit
from app.state import TurnState

PLACEHOLDER_PROMPT = "You are Socrates of Athens. Answer in everyday words and ask short questions."


def persona_node(state: TurnState, deps: Deps) -> dict:
    persona_id = state["persona_id"]
    emit("voice", speaker="persona", persona_id=persona_id)
    chunks = []
    if state["safety"]["needs_retrieval"]:
        chunks = deps.retrieve(persona_id, state["messages"][-1].content,
                               k=deps.config.k, min_score=deps.config.min_score)
    parts = []
    for delta in deps.generate(PLACEHOLDER_PROMPT, state["messages"]):
        emit("token", text=delta)
        parts.append(delta)
    reply = "".join(parts)
    return {"retrieved": chunks, "reply": reply, "citations": [],
            "messages": [AIMessage(reply, name=persona_id)]}
