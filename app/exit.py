"""Exit flow (M-05). The persona steps aside and a system voice hands over.

The reply is a fixed text, not generated, so it can never take the persona's
voice, debate the user's reasons or mention means. The wording is a draft for
the team to review; the resource list comes from the UI/UX teammates.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from app.deps import Deps
from app.events import emit
from app.state import TurnState

HANDOVER = (
    "It sounds like you are carrying something very heavy right now, and I'm glad you said it. "
    "I'm going to set the philosopher aside so we can focus on you. You don't have to face this alone: "
    "the people below are available now and want to help."
)
STILL_HERE = (
    "I'm still here with you, and the philosopher will stay aside for now. "
    "If you might be in danger, please reach out to one of the people below right now."
)


def exit_node(state: TurnState, deps: Deps) -> dict:
    first = state.get("mode") != "support"
    text = HANDOVER if first else STILL_HERE
    emit("voice", speaker="system", persona_id=None)
    emit("token", text=text)
    emit("exit", reason="tier_3" if first else "support_mode", resources=list(deps.resources))
    return {"mode": "support", "retrieved": [], "reply": text, "citations": [],
            "messages": [AIMessage(text, name="system")]}
