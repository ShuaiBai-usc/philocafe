"""Safety models (Jev, fallback), the decision log and the exit resources. Offline only:
Jev runs over httpx.MockTransport and the fallback over a stub client."""

import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.config import SafetyConfig
from app.exit import load_resources
from app.fakes import FakeSafetyModel, fake_deps
from app.graph import build_graph, run_turn
from app.safety import jev as jev_module
from app.safety.fallback import FallbackModel, TierEstimate
from app.safety.jev import URL, JevModel
from app.safety.tiers import TIERS

CFG = SafetyConfig()
HISTORY = [HumanMessage("first"), AIMessage("a reply", name="socrates"), HumanMessage("TEST_MESSAGE")]


def jev_answer(probs=(0.7, 0.2, 0.08, 0.02), noul=0.8, back=0.1, model="jev-1.13.0"):
    return {"model": model,
            "answers": {"risk_tier": {"type": "choice", "choice": "everyday", "confidence": 0.9,
                                      "probabilities": dict(zip(TIERS, probs))},
                        "needs_retrieval": {"type": "noul", "noul": noul},
                        "wants_persona_back": {"type": "noul", "noul": back}},
            "usage": {"input_tokens": 300, "output_tokens": 20}}


def jev_with(handler):
    return JevModel(CFG, api_key="test-key", transport=httpx.MockTransport(handler))


def test_jev_request_and_answer():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=jev_answer())

    scores = jev_with(handler).classify(HISTORY)
    assert seen["url"] == URL
    assert seen["auth"] == "Bearer test-key"
    body = seen["body"]
    assert body["model"] == CFG.jev_model
    assert body["state"]["latest_user_message"] == "TEST_MESSAGE"
    assert [t["speaker"] for t in body["state"]["earlier_turns"]] == ["user", "philosopher"]
    assert body["questions"]["risk_tier"]["type"] == "choice"
    assert list(body["questions"]["risk_tier"]["criteria"]) == list(TIERS)
    assert body["questions"]["needs_retrieval"]["type"] == "noul"
    assert body["questions"]["wants_persona_back"]["type"] == "noul"
    assert scores == {"tier_probs": {0: 0.7, 1: 0.2, 2: 0.08, 3: 0.02}, "needs_retrieval": True,
                      "wants_persona_back": False,
                      "model_version": "jev-1.13.0"}


def test_jev_low_noul_means_no_retrieval():
    scores = jev_with(lambda r: httpx.Response(200, json=jev_answer(noul=0.3))).classify(HISTORY)
    assert scores["needs_retrieval"] is False


@pytest.mark.parametrize("handler, error", [
    (lambda r: httpx.Response(529, json={"error": "overloaded"}), httpx.HTTPStatusError),
    (lambda r: httpx.Response(200, json={"model": "jev", "answers": {}}), KeyError),
])
def test_jev_errors_raise(handler, error):
    with pytest.raises(error):
        jev_with(handler).classify(HISTORY)


def test_jev_missing_key_raises(monkeypatch):
    def no_key(name):
        raise KeyError(name)
    monkeypatch.setattr(jev_module, "secret", no_key)
    model = JevModel(CFG, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=jev_answer())))
    with pytest.raises(KeyError):
        model.classify(HISTORY)


class StubAnthropic:
    """Stands in for anthropic.Anthropic: records parse() calls and returns a canned response."""

    def __init__(self, response):
        self.calls = []
        self.messages = SimpleNamespace(parse=self._parse)
        self._response = response

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def haiku_response(estimate, stop_reason="end_turn"):
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=estimate, model="claude-haiku-5-5")


def test_fallback_normalizes_probabilities():
    estimate = TierEstimate(everyday=2.0, mild_distress=1.0, elevated=1.0, high_risk=0.0, needs_retrieval=False,
                            wants_persona_back=True)
    client = StubAnthropic(haiku_response(estimate))
    scores = FallbackModel(CFG, client=client).classify(HISTORY)
    assert scores["tier_probs"] == {0: 0.5, 1: 0.25, 2: 0.25, 3: 0.0}
    assert scores["needs_retrieval"] is False and scores["wants_persona_back"] is True
    assert scores["model_version"] == "claude-haiku-5-5"
    call = client.calls[0]
    assert call["model"] == CFG.fallback_model
    assert call["output_format"] is TierEstimate
    assert json.loads(call["messages"][0]["content"])["latest_user_message"] == "TEST_MESSAGE"


@pytest.mark.parametrize("response", [
    haiku_response(None, stop_reason="refusal"),
    haiku_response(TierEstimate(everyday=0, mild_distress=0, elevated=0, high_risk=0, needs_retrieval=True,
                               wants_persona_back=False)),
])
def test_fallback_without_usable_answer_raises(response):
    with pytest.raises((RuntimeError, ValueError)):
        FallbackModel(CFG, client=StubAnthropic(response)).classify(HISTORY)


def test_jev_timeout_falls_back_and_is_logged():
    def timeout(request):
        raise httpx.ReadTimeout("timed out", request=request)
    deps = fake_deps(safety_models=[jev_with(timeout), FakeSafetyModel("fallback")])
    graph = build_graph(deps)
    events = list(run_turn(graph, "t1", "hello", "socrates"))
    safety = next(e["data"] for e in events if e["type"] == "safety")
    assert safety["source"] == "fallback"
    (record,) = deps.decision_log.records
    assert (record.thread_id, record.turn, record.tier, record.source) == ("t1", 1, 0, "fallback")
    assert record.errors == ("jev: ReadTimeout",)


def test_decision_log_counts_turns_and_failures():
    deps = fake_deps(safety_models=[FakeSafetyModel("jev", fail=True), FakeSafetyModel("fallback", fail=True)])
    graph = build_graph(deps)
    list(run_turn(graph, "t1", "hello", "socrates"))
    list(run_turn(graph, "t1", "again", "socrates"))
    turns = [(r.turn, r.tier, r.model_version, len(r.errors)) for r in deps.decision_log.for_thread("t1")]
    assert turns == [(1, 3, "fail-closed", 2), (2, 3, "fail-closed", 2)]


def test_resources_file_loads():
    resources = load_resources()
    assert resources and all(r["name"] and r["contact"] for r in resources)
