"""Persona configs (FR-10): one YAML file per persona under personas/."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.config import ROOT

PERSONAS_DIR = ROOT / "personas"
TIER2_MARKS = {"cautions_against", "open_to_misreading"}


@dataclass(frozen=True)
class PersonaConfig:
    id: str
    name: str
    era: str
    tagline: str
    corpus: str                     # persona id in the corpus database
    prompt: str
    style: tuple[str, ...] = ()
    k: int | None = None
    min_score: float | None = None
    tier2_passages: dict[str, str] = field(default_factory=dict)


def load_persona(path: Path) -> PersonaConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    tier2 = raw.get("tier2_passages") or {}
    bad = {cid: mark for cid, mark in tier2.items() if mark not in TIER2_MARKS}
    if bad:
        raise ValueError(f"{path.name}: tier2_passages marks must be one of {sorted(TIER2_MARKS)}: {bad}")
    retrieval = raw.get("retrieval") or {}
    return PersonaConfig(id=raw["id"], name=raw["name"], era=raw.get("era", ""), tagline=raw.get("tagline", ""),
                         corpus=raw.get("corpus", raw["id"]), prompt=raw["prompt"].strip(),
                         style=tuple(raw.get("style") or ()), k=retrieval.get("k"),
                         min_score=retrieval.get("min_score"), tier2_passages=dict(tier2))


def load_personas(directory: Path = PERSONAS_DIR) -> dict[str, PersonaConfig]:
    personas = [load_persona(p) for p in sorted(directory.glob("*.yaml"))]
    return {p.id: p for p in personas}
