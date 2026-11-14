"""Episodic memory organ: ordered provenance-preserving event recording."""

from __future__ import annotations

import time
from typing import Any

from organism.kernel.contracts import OrganContract, OrganReport, StepStatus
from organism.memory.storage import SQLiteMemoryStore


class EpisodicMemoryOrgan(OrganContract):
    name = "episodic_memory"
    critical = True

    def __init__(self, store: SQLiteMemoryStore) -> None:
        self._store = store

    def execute(self, context: dict[str, Any]) -> OrganReport:
        t0 = time.perf_counter()
        episode_id = self._store.insert_episode(
            cycle_id=str(context["cycle_id"]),
            event_id=str(context["event_id"]),
            source=str(context["source"]),
            trust_level=str(context["trust_level"]),
            event_content=str(context["event_content"]),
            action_taken=str(context["action_taken"]),
            outcome_status=str(context["outcome_status"]),
            outcome_summary=str(context["outcome_summary"]),
            metadata=dict(context.get("metadata", {})),
        )
        return OrganReport(
            organ_name=self.name,
            status=StepStatus.OK,
            payload={"episode_id": episode_id},
            confidence=1.0,
            deterministic=True,
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
        )
