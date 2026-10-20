"""Jev (TypeSafe System One) as the safety model.

One request per turn asks two questions about the conversation: a Choice for
the risk tier, whose per-option probabilities become `tier_probs`, and a Noul
for whether retrieval would help. Any HTTP error, timeout or malformed answer
raises, and the safety node moves on to the fallback.
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx
from langchain_core.messages import AnyMessage

from app.config import SafetyConfig, secret
from app.deps import SafetyScores
from app.safety.tiers import (RETRIEVAL_CRITERIA, RETRIEVAL_INSTRUCTIONS, TIER_INSTRUCTIONS, TIERS,
                              conversation_state)

URL = "https://api.typesafe.ai/v1/systemone"


def request_body(history: Sequence[AnyMessage], model: str) -> dict:
    return {
        "model": model,
        "state": conversation_state(history),
        "questions": {
            "risk_tier": {"type": "choice", "instructions": TIER_INSTRUCTIONS,
                          "criteria": {name: desc for name, (_, desc) in TIERS.items()}},
            "needs_retrieval": {"type": "noul", "instructions": RETRIEVAL_INSTRUCTIONS,
                                "criteria": RETRIEVAL_CRITERIA},
        },
    }


def parse_answers(body: dict) -> SafetyScores:
    """Raises KeyError or ValueError if the answer is not what was asked for."""
    answers = body["answers"]
    probs = answers["risk_tier"]["probabilities"]
    tier_probs = {tier: float(probs[name]) for name, (tier, _) in TIERS.items()}
    return SafetyScores(tier_probs=tier_probs,
                        needs_retrieval=float(answers["needs_retrieval"]["noul"]) >= 0.5,
                        model_version=str(body["model"]))


class JevModel:
    source = "jev"

    def __init__(self, cfg: SafetyConfig, api_key: str | None = None,
                 transport: httpx.BaseTransport | None = None):
        self.cfg = cfg
        self._api_key = api_key
        self._http = httpx.Client(timeout=cfg.jev_timeout_s, transport=transport)

    def classify(self, history: Sequence[AnyMessage]) -> SafetyScores:
        # The key is read on first use, so a missing key fails this call (and
        # the fallback takes over) rather than stopping the app at startup.
        key = self._api_key or secret("JEV_API_KEY")
        response = self._http.post(URL, json=request_body(history, self.cfg.jev_model),
                                   headers={"Authorization": f"Bearer {key}"})
        response.raise_for_status()
        return parse_answers(response.json())
