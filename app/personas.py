"""Persona configs (FR-10): one YAML file per persona under personas/."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.config import ROOT
from app.mood import CALM, MAX_MOODS

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
    texts: str = "your writings"    # what the corpus is, as the persona and the safety check name it
    style: tuple[str, ...] = ()
    k: int | None = None
    min_score: float | None = None
    tier2_passages: dict[str, str] = field(default_factory=dict)
    voice: str = "ash"              # stock text-to-speech voice (7.6); never a real person's voice
    voice_style: str = ""           # one-line speaking style sent with each sentence
    elevenlabs_voice: str = ""      # ElevenLabs voice id, when voice.provider is elevenlabs
    elevenlabs_by_language: dict[str, str] = field(default_factory=dict)   # e.g. {"zh": id} for Chinese replies
    moods: tuple[str, ...] = (CALM,)   # 7.5: at most six, intellectual only, always with attentive


def load_persona(path: Path) -> PersonaConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    tier2 = raw.get("tier2_passages") or {}
    bad = {cid: mark for cid, mark in tier2.items() if mark not in TIER2_MARKS}
    if bad:
        raise ValueError(f"{path.name}: tier2_passages marks must be one of {sorted(TIER2_MARKS)}: {bad}")
    moods = tuple(str(m).strip().lower() for m in (raw.get("moods") or [CALM]))
    if CALM not in moods or len(moods) > MAX_MOODS or len(set(moods)) != len(moods):
        raise ValueError(f"{path.name}: moods must be at most {MAX_MOODS} distinct labels including {CALM!r}")
    retrieval = raw.get("retrieval") or {}
    return PersonaConfig(id=raw["id"], name=raw["name"], era=raw.get("era", ""), tagline=raw.get("tagline", ""),
                         corpus=raw.get("corpus", raw["id"]), prompt=raw["prompt"].strip(),
                         texts=raw.get("texts") or PersonaConfig.texts,
                         style=tuple(raw.get("style") or ()), k=retrieval.get("k"),
                         min_score=retrieval.get("min_score"), tier2_passages=dict(tier2),
                         voice=(raw.get("voice") or {}).get("name", PersonaConfig.voice),
                         voice_style=((raw.get("voice") or {}).get("style") or "").strip(),
                         elevenlabs_voice=((raw.get("voice") or {}).get("elevenlabs") or "").strip(),
                         elevenlabs_by_language={str(k).lower(): str(v).strip() for k, v in
                                                 ((raw.get("voice") or {}).get("elevenlabs_by_language") or {}).items()},
                         moods=moods)


def load_personas(directory: Path = PERSONAS_DIR) -> dict[str, PersonaConfig]:
    personas = [load_persona(p) for p in sorted(directory.glob("*.yaml"))]
    return {p.id: p for p in personas}
