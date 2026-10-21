"""Safety decision log (FR-23): turn, tier, probability, threshold, model and version.

Kept in memory for the session only (open decision D8: nothing is written to
disk during the showcase). The eval harness writes its own CSV per run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class DecisionRecord:
    thread_id: str
    turn: int
    tier: int
    probability: float
    threshold: float
    source: str
    model_version: str
    errors: tuple[str, ...] = ()     # models that failed before this decision, e.g. "jev: ReadTimeout"
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


class DecisionLog:
    def __init__(self) -> None:
        self.records: list[DecisionRecord] = []

    def record(self, rec: DecisionRecord) -> None:
        self.records.append(rec)

    def for_thread(self, thread_id: str) -> list[DecisionRecord]:
        return [r for r in self.records if r.thread_id == thread_id]
