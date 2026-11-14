"""Global Cognitive Workspace: shared, capacity-bounded active broadcast buffer."""

from __future__ import annotations

import time
from typing import Any

from organism.kernel.contracts import OrganContract, OrganReport, StepStatus, utc_now_iso


class GlobalWorkspaceOrgan(OrganContract):
    name = "workspace"
    critical = False

    def __init__(self, capacity: int = 7) -> None:
        self.capacity = capacity

    def execute(self, context: dict[str, Any]) -> OrganReport:
        t0 = time.perf_counter()
        ranked = list(context.get("attention_ranked", []))
        cycle_number = int(context.get("cycle_number", 1))
        bounded = ranked[: self.capacity]

        workspace_items = [
            {
                "slot": idx + 1,
                "item_id": item["item_id"],
                "layer": item["layer"],
                "summary": item["summary"],
                "epistemic_type": item["epistemic_type"],
                "salience": item["salience"],
                "source": item["source"],
                "expires_at_cycle": cycle_number + 3,
                "broadcast_at": utc_now_iso(),
            }
            for idx, item in enumerate(bounded)
        ]

        return OrganReport(
            organ_name=self.name,
            status=StepStatus.OK,
            payload={
                "capacity": self.capacity,
                "occupied": len(workspace_items),
                "items": workspace_items,
            },
            confidence=0.95,
            deterministic=True,
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
        )
