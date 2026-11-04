"""Moderator (M-02). It keeps the persona the user selected in the café;
routing between personas (FR-13) comes at the final. Whether to retrieve is
taken from the safety decision by the persona node."""

from __future__ import annotations

from app.deps import Deps
from app.state import TurnState


def moderator_node(state: TurnState, deps: Deps) -> dict:
    return {"persona_id": state.get("persona_id") or deps.config.default_persona}
