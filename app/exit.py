"""Exit flow (M-05). The persona steps aside and a system voice hands over.

The reply is a fixed text, not generated, so it can never take the persona's
voice, debate the user's reasons or mention means. The handover wording is the
UI/UX team's (prototype screen 07); the resource list comes from them too.
Later turns stay here until the user asks for the persona back and risk has
dropped (FR-32, decided by the safety node).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from langchain_core.messages import AIMessage

from app.config import ROOT
from app.deps import Deps
from app.events import emit
from app.state import TurnState

RESOURCES_PATH = ROOT / "data" / "resources.yaml"

HANDOVER = (
    "Let's take a moment. You deserve support with what you're carrying. "
    "We're pausing this conversation to make room for that."
)
STILL_HERE = (
    "I'm still here with you, and {name} is staying aside for now. When you feel ready, you can ask "
    "{name} to come back. If you might be in danger, please reach out to one of the people below right now."
)


def load_resources(path: Path = RESOURCES_PATH) -> list[dict]:
    resources = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [{"name": r["name"], "contact": r["contact"]} for r in resources]


def exit_node(state: TurnState, deps: Deps) -> dict:
    first = state.get("mode") != "support"
    persona = deps.personas.get(state.get("persona_id", ""))
    text = HANDOVER if first else STILL_HERE.format(name=persona.name if persona else "the philosopher")
    emit("voice", speaker="system", persona_id=None)
    emit("token", text=text)
    emit("exit", reason="tier_3" if first else "support_mode", resources=list(deps.resources))
    return {"mode": "support", "retrieved": [], "reply": text, "citations": [],
            "messages": [AIMessage(text, name="system")]}
