"""Safety node (M-01): classifies every turn before any persona reply.

The models are tried in order (Jev, then the fallback). If every one fails,
the turn is escalated to tier 3 (fail closed, ADR-07). The tier is decided
here from the tier probabilities and the thresholds in config, never by the
model's own top choice. Every decision is logged (FR-23).
"""

from __future__ import annotations

import logging
from dataclasses import replace

import httpx
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from app.config import SafetyConfig
from app.deps import Deps, SafetyScores
from app.events import emit
from app.safety.log import DecisionRecord
from app.state import SafetyDecision, TurnState

log = logging.getLogger(__name__)

FAIL_CLOSED = SafetyScores(tier_probs={0: 0.0, 1: 0.0, 2: 0.0, 3: 1.0}, needs_retrieval=False,
                           wants_persona_back=False, model_version="fail-closed")


def decide(tier_probs: dict[int, float], cfg: SafetyConfig) -> tuple[int, float, float]:
    """Apply the decision rule of design doc section 8.

    Returns (tier, probability, threshold): the probability that was compared
    and the threshold it was compared with. Below both thresholds it reports
    P(2) + P(3) against theta2, i.e. how close the turn came to escalating.
    """
    p3 = tier_probs.get(3, 0.0)
    p23 = tier_probs.get(2, 0.0) + p3
    if p3 >= cfg.theta3:
        return 3, p3, cfg.theta3
    if p23 >= cfg.theta2:
        return 2, p23, cfg.theta2
    tier = 1 if tier_probs.get(1, 0.0) > tier_probs.get(0, 0.0) else 0
    return tier, p23, cfg.theta2


def describe_error(e: Exception) -> str:
    # Type and HTTP status only: messages can carry user text or request details.
    if isinstance(e, httpx.HTTPStatusError):
        return f"{type(e).__name__} {e.response.status_code}"
    return type(e).__name__


def since_pause(messages: list[AnyMessage]) -> list[AnyMessage]:
    """In support mode: the turns from the system's handover on. The message that caused the
    pause stays out, so it does not keep the risk up after the user says how they are now."""
    last_persona = max((k for k, m in enumerate(messages)
                        if isinstance(m, AIMessage) and m.name != "system"), default=-1)
    start = next((k for k in range(last_persona + 1, len(messages))
                  if isinstance(messages[k], AIMessage) and messages[k].name == "system"), None)
    return messages[start:] if start is not None else messages


def safety_node(state: TurnState, deps: Deps) -> dict:
    cfg = deps.config.safety
    support = state.get("mode") == "support"
    messages = since_pause(state["messages"]) if support else state["messages"]
    history = messages[-(2 * cfg.history_turns + 1):]
    errors = []
    for model in deps.safety_models:
        try:
            scores, source = model.classify(history), model.source
            break
        except Exception as e:   # any failure moves on to the next model
            errors.append(f"{model.source}: {describe_error(e)}")
            log.warning("safety model failed: %s", errors[-1])
    else:
        scores, source = FAIL_CLOSED, "fallback"

    # FR-32: in support mode the return has its own threshold, so it can be tuned
    # without touching detection in ordinary conversation.
    tier, probability, threshold = decide(scores["tier_probs"],
                                          replace(cfg, theta2=cfg.return_theta2) if support else cfg)
    # FR-32: in support mode, `route` names the persona the user asked to have back: by the
    # "ready to come back" button, or in their own words. Whether risk has dropped enough is
    # the graph's edge rule (route_after_safety).
    asked_back = support and (state.get("return_request", False) or scores.get("wants_persona_back", False))
    decision = SafetyDecision(tier=tier, tier_probs=scores["tier_probs"],
                              needs_retrieval=scores["needs_retrieval"],
                              route=state["persona_id"] if asked_back else None,
                              source=source, model_version=scores["model_version"])
    turn = sum(isinstance(m, HumanMessage) for m in state["messages"])
    deps.decision_log.record(DecisionRecord(
        thread_id=state["thread_id"], turn=turn, tier=tier, probability=probability, threshold=threshold,
        source=source, model_version=decision["model_version"], errors=tuple(errors)))
    emit("safety", tier=tier, probability=round(probability, 4), threshold=threshold,
         source=source, model_version=decision["model_version"])
    return {"safety": decision}
