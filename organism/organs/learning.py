"""Learning & consolidation organ: converts cycle experience into verified or candidate memory updates."""

from __future__ import annotations

import time
from typing import Any

from organism.kernel.contracts import EpistemicType, MemoryStatus, OrganContract, OrganReport, StepStatus
from organism.memory.consolidation import MemoryConsolidator


class LearningOrgan(OrganContract):
    name = "learning"
    critical = False

    def __init__(self, consolidator: MemoryConsolidator) -> None:
        self._consolidator = consolidator

    def execute(self, context: dict[str, Any]) -> OrganReport:
        t0 = time.perf_counter()
        episode_id = str(context.get("episode_id", ""))
        reasoning_payload = context.get("reasoning_payload", {})
        perception = context.get("perception", {})
        outcome_status = str(context.get("outcome_status", "COMPLETED"))

        candidates: list[dict[str, Any]] = []
        triple = reasoning_payload.get("triple")
        if isinstance(triple, dict) and outcome_status == "COMPLETED":
            ep_type = reasoning_payload.get("epistemic_type", EpistemicType.HYPOTHESIS.value)
            is_trusted_fact = (
                ep_type == EpistemicType.FACT.value
                and not perception.get("is_untrusted_data", True)
            )
            candidates.append(
                {
                    "subject": triple["subject"],
                    "predicate": triple["predicate"],
                    "object_value": triple["object_value"],
                    "epistemic_type": ep_type,
                    "confidence": 0.9 if is_trusted_fact else 0.5,
                    "status": MemoryStatus.VERIFIED.value if is_trusted_fact else MemoryStatus.CANDIDATE.value,
                }
            )

        if not episode_id or not candidates:
            return OrganReport(
                organ_name=self.name,
                status=StepStatus.OK,
                payload={"consolidated_count": 0, "details": {}},
                confidence=1.0,
                deterministic=True,
                duration_ms=round((time.perf_counter() - t0) * 1000, 3),
            )

        result = self._consolidator.consolidate_candidates(candidates, episode_id=episode_id)
        return OrganReport(
            organ_name=self.name,
            status=StepStatus.OK,
            payload={
                "consolidated_count": len(result["stored_fact_ids"]),
                "details": result,
            },
            confidence=0.95,
            deterministic=True,
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
        )
