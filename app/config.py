"""App settings: tunable values from config.yaml, secrets from the environment.

Secrets are read on demand with `secret()` and are never stored on the config
object, so printing or logging a Config cannot leak a key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"


@dataclass(frozen=True)
class SafetyConfig:
    theta3: float = 0.5
    theta2: float = 0.5
    jev_model: str = "jev-latest"
    jev_timeout_s: float = 2.0
    history_turns: int = 4
    fallback_model: str = "claude-haiku-5-5"
    fallback_timeout_s: float = 5.0


@dataclass(frozen=True)
class Config:
    safety: SafetyConfig = SafetyConfig()
    default_persona: str = "socrates"
    voice_model: str = "claude-sonnet-5-5"
    voice_effort: str = "low"        # conversational replies; keeps the first token fast
    k: int = 5
    min_score: float | None = None   # None: the retrieval default
    translate_model: str = "claude-haiku-5-5"   # for non-English retrieval queries
    translate_timeout_s: float = 5.0


def load_config(path: Path = CONFIG_PATH) -> Config:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    persona = raw.get("persona", {})
    retrieval = raw.get("retrieval", {})
    return Config(
        safety=SafetyConfig(**raw.get("safety", {})),
        default_persona=persona.get("default", Config.default_persona),
        voice_model=persona.get("voice_model", Config.voice_model),
        voice_effort=persona.get("voice_effort", Config.voice_effort),
        k=retrieval.get("k", Config.k),
        min_score=retrieval.get("min_score"),
        translate_model=retrieval.get("translate_model", Config.translate_model),
        translate_timeout_s=retrieval.get("translate_timeout_s", Config.translate_timeout_s),
    )


def secret(name: str) -> str:
    """Return an API key from the environment (.env is loaded first).

    Raises KeyError naming the variable, never its value.
    """
    load_dotenv(ROOT / ".env", override=False)
    value = os.environ.get(name, "").strip()
    if not value:
        raise KeyError(f"{name} is not set; add it to .env")
    return value
