"""Semantic memory organ: durable assertions with temporal validity and contradiction checks."""

from __future__ import annotations

import time
from typing import Any

from organism.kernel.contracts import EpistemicType, MemoryStatus, OrganContract, OrganReport, StepStatus
from organism.memory.knowledge_graph import TemporalKnowledgeGraph
from organism.memory.storage import SQLiteMemoryStore


class SemanticMemoryOrgan(OrganContract):
    name = "semantic_memory"
    critical = False

    def __init__(self, store: SQLiteMemoryStore, kg: TemporalKnowledgeGraph) -> None:
        self._store = store
        self._kg = kg

    def execute(self, context: dict[str, Any]) -> OrganReport:
        t0 = time.perf_counter()
        action = context.get("action", "query")
        if action == "record":
            res = self._kg.record_assertion(
                subject=str(context["subject"]),
                predicate=str(context["predicate"]),
                object_value=str(context["object_value"]),
                epistemic_type=EpistemicType(context.get("epistemic_type", EpistemicType.FACT.value)),
                confidence=float(context.get("confidence", 0.85)),
                source_episode_id=str(context["episode_id"]),
                status=MemoryStatus(context.get("status", MemoryStatus.VERIFIED.value)),
            )
            return OrganReport(
                organ_name=self.name,
                status=StepStatus.OK,
                payload=res,
                confidence=1.0,
                deterministic=True,
                duration_ms=round((time.perf_counter() - t0) * 1000, 3),
            )

        facts = self._store.list_semantic_facts(include_invalidated=False, limit=30)
        return OrganReport(
            organ_name=self.name,
            status=StepStatus.OK,
            payload={"active_facts": facts},
            confidence=1.0,
            deterministic=True,
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
        )
