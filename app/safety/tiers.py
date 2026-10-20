"""Risk tier definitions (design doc section 8), shared by Jev and the
fallback so both judge a turn against the same words.

The annotation guidance is folded in: judge the latest message in the
context of the earlier turns, by the user's own situation; quoting or
discussing a philosopher on death or suicide is not by itself tier 2 or 3.
"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

# option name -> (tier, description)
TIERS: dict[str, tuple[int, str]] = {
    "everyday": (0, "Ordinary questions, dilemmas, or curiosity about a book or idea, with no sign of "
                    "distress. Asking what a philosopher said about death or suicide belongs here when "
                    "the user's own situation shows no distress."),
    "mild_distress": (1, "Stress, sadness, frustration or a setback, with no sign of harm to self or others."),
    "elevated": (2, "Lasting hopelessness, worthlessness or isolation; vague talk of not wanting to go on, "
                    "with no plan; or reading the philosopher as a justification for harming oneself or others."),
    "high_risk": (3, "Intent, plan or means for self-harm or suicide; intent to harm others; or immediate danger."),
}

TIER_INSTRUCTIONS = (
    "Which risk tier fits latest_user_message? Judge it in the context of earlier_turns, "
    "by the user's own situation rather than the topic under discussion."
)

RETRIEVAL_INSTRUCTIONS = (
    "Would quoting passages from Plato's dialogues help the philosopher answer latest_user_message?"
)
# FR-32: in support mode the persona returns only if the user asks for it and risk has dropped.
RETURN_INSTRUCTIONS = "Is the user asking to go back to talking with the philosopher in latest_user_message?"
RETURN_CRITERIA = {
    "true": "The user asks for the philosopher to come back, or to continue the earlier conversation with them.",
    "false": "Anything else, including thanks, more about how they feel, or questions for the support system.",
}

RETRIEVAL_CRITERIA = {
    "true": "The message raises a question, idea or dilemma that Socrates discusses, or asks what he said or thought.",
    "false": "A greeting, thanks, small talk, or a question about the app itself.",
}


def speaker(message: AnyMessage) -> str:
    if isinstance(message, HumanMessage):
        return "user"
    if isinstance(message, AIMessage) and message.name == "system":
        return "support system"
    return "philosopher"


def conversation_state(history: Sequence[AnyMessage]) -> dict:
    """The state both safety models see: earlier turns plus the latest user message."""
    *earlier, latest = history
    return {
        "earlier_turns": [{"speaker": speaker(m), "text": m.content} for m in earlier],
        "latest_user_message": latest.content,
    }
