"""Working memory organ: rapid bounded state for the current cycle."""

from __future__ import annotations

import time
from typing import Any

from organism.kernel.contracts import EpistemicType, OrganContract, OrganReport, StepStatus
from organism.memory.storage import SQLiteMemoryStore


class WorkingMemoryOrgan(OrganContract):
    name = "working_memory"
    critical = False

    def __init__(self, store: SQLiteMemoryStore, capacity: int = 12, ttl_cycles: int = 6) -> None:
        self._store = store
        self.capacity = capacity
        self.ttl_cycles = ttl_cycles

    def execute(self, context: dict[str, Any]) -> OrganReport:
        t0 = time.perf_counter()
        cycle_number = int(context.get("cycle_number", 1))
        expired_count = self._store.expire_working_memory(cycle_number)

        key = str(context.get("slot_key", f"cycle_{cycle_number}_focus"))
        value = context.get("slot_value", {})
        priority = float(context.get("priority", 0.8))
        ep_type = EpistemicType(context.get("epistemic_type", EpistemicType.UNKNOWN.value))
        source = str(context.get("source", "kernel"))

        self._store.upsert_working_memory(
            key=key,
            value=value,
            priority=priority,
            epistemic_type=ep_type,
            source=source,
            expires_at_cycle=cycle_number + self.ttl_cycles,
            capacity=self.capacity,
        )

        slots = self._store.list_working_memory()
        return OrganReport(
            organ_name=self.name,
            status=StepStatus.OK,
            payload={"expired_count": expired_count, "active_slots": len(slots), "slots": slots},
            confidence=1.0,
            deterministic=True,
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
        )
