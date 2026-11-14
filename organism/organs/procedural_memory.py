"""Procedural memory organ: stores tested workflows with explicit trust status lifecycle."""

from __future__ import annotations

import time
from typing import Any

from organism.kernel.contracts import MemoryStatus, OrganContract, OrganReport, StepStatus
from organism.memory.storage import SQLiteMemoryStore


class ProceduralMemoryOrgan(OrganContract):
    name = "procedural_memory"
    critical = False

    def __init__(self, store: SQLiteMemoryStore) -> None:
        self._store = store
        self._ensure_baseline_procedures()

    def _ensure_baseline_procedures(self) -> None:
        if not self._store.list_procedures():
            self._store.upsert_procedure(
                name="deterministic_ast_math",
                status=MemoryStatus.ACTIVE,
                definition={"engine": "ast_safe_eval", "deterministic": True, "requires_llm": False},
            )
            self._store.upsert_procedure(
                name="epistemic_triple_consolidation",
                status=MemoryStatus.VERIFIED,
                definition={"engine": "temporal_kg", "deterministic": True, "requires_llm": False},
            )

    def execute(self, context: dict[str, Any]) -> OrganReport:
        t0 = time.perf_counter()
        procs = self._store.list_procedures()
        return OrganReport(
            organ_name=self.name,
            status=StepStatus.OK,
            payload={"procedures": procs},
            confidence=1.0,
            deterministic=True,
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
        )
