"""Disk cache for Jev and Claude calls during eval runs (CLAUDE.md: cache LLM calls).

Each call is keyed by a hash of everything that shapes its answer. Errors are
never cached, and a reply is cached only once it has streamed to the end.
Each wrapper counts calls and hits, so a run can tell which rows came from the
cache and leave them out of latency figures.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Sequence
from pathlib import Path

from langchain_core.messages import AnyMessage

from app.deps import SafetyScores


def _messages(messages: Sequence[AnyMessage]) -> list:
    return [[type(m).__name__, getattr(m, "name", None), m.content] for m in messages]


class DiskCache:
    def __init__(self, root: Path):
        self.root = root

    @staticmethod
    def key(*parts) -> str:
        blob = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str):
        path = self._path(key)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def put(self, key: str, value) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class CachedSafetyModel:
    def __init__(self, model, cache: DiskCache, tag: str):
        self.model, self.cache, self.tag = model, cache, tag     # tag: model name and settings
        self.source = model.source
        self.calls = self.hits = 0

    def classify(self, history: Sequence[AnyMessage]) -> SafetyScores:
        self.calls += 1
        key = self.cache.key("safety", self.source, self.tag, _messages(history))
        hit = self.cache.get(key)
        if hit is not None:
            self.hits += 1
            return SafetyScores(tier_probs={int(t): p for t, p in hit["tier_probs"].items()},
                                needs_retrieval=hit["needs_retrieval"], model_version=hit["model_version"])
        scores = self.model.classify(history)
        self.cache.put(key, scores)
        return scores


class CachedVoice:
    def __init__(self, voice, cache: DiskCache, tag: str):
        self.voice, self.cache, self.tag = voice, cache, tag
        self.calls = self.hits = 0

    def __call__(self, system: str, messages: Sequence[AnyMessage]) -> Iterator[str]:
        self.calls += 1
        key = self.cache.key("voice", self.tag, system, _messages(messages))
        hit = self.cache.get(key)
        if hit is not None:
            self.hits += 1
            yield from hit
            return
        pieces = []
        for piece in self.voice(system, messages):
            pieces.append(piece)
            yield piece
        self.cache.put(key, pieces)


class CachedTranslate:
    def __init__(self, translate, cache: DiskCache, tag: str):
        self.translate, self.cache, self.tag = translate, cache, tag
        self.calls = self.hits = 0

    def __call__(self, text: str) -> str:
        self.calls += 1
        key = self.cache.key("translate", self.tag, text)
        hit = self.cache.get(key)
        if hit is not None:
            self.hits += 1
            return hit
        result = self.translate(text)
        self.cache.put(key, result)
        return result
