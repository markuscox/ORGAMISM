"""Evidence-based Learning & Consolidation organ: OBSERVED -> CANDIDATE -> EVIDENCE_CHECKED -> VERIFIED | REJECTED."""

from __future__ import annotations

import time
from typing import Any

from organism.kernel.contracts import (
    EpistemicType,
    MemoryStatus,
    OrganContract,
    OrganReport,
    StepStatus,
    TrustLevel,
)
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
        refrain = bool(context.get("refrain_recommended", False))

        candidates: list[dict[str, Any]] = []
        triple = reasoning_payload.get("triple")
        res_type = reasoning_payload.get("resolution_type", "")

        if isinstance(triple, dict) and outcome_status == "COMPLETED":
            ep_type = reasoning_payload.get("epistemic_type", EpistemicType.HYPOTHESIS.value)
            trust_level = str(perception.get("trust_level", TrustLevel.UNTRUSTED_EXTERNAL.value))
            source = str(perception.get("source", "kernel"))
            det_proof = res_type == "deterministic_math"

            # Refrain from storing ungrounded LLM/synthetic claims when metacognition recommends abstention
            if refrain and res_type != "symbolic_assertion":
                triple = None
            else:
                # Stage 2 rule: neither trusted operator nor LLM output jumps directly to VERIFIED.
                # Uncorroborated assertions always begin as CANDIDATE until evidence-checked.
                candidates.append(
                    {
                        "subject": triple["subject"],
                        "predicate": triple["predicate"],
                        "object_value": triple["object_value"],
                        "epistemic_type": ep_type,
                        "confidence": 0.6 if trust_level != TrustLevel.UNTRUSTED_EXTERNAL.value else 0.35,
                        "status": MemoryStatus.CANDIDATE.value,
                        "source": source,
                        "trust_level": trust_level,
                        "deterministic_proof": det_proof,
                    }
                )

        if not episode_id or not candidates:
            return OrganReport(
                organ_name=self.name,
                status=StepStatus.OK,
                payload={
                    "consolidated_count": 0,
                    "skipped_due_to_abstention": refrain,
                    "details": {},
                },
                confidence=1.0,
                deterministic=True,
                duration_ms=round((time.perf_counter() - t0) * 1000, 3),
            )

        result = self._consolidator.consolidate_candidates(candidates, episode_id=episode_id)
        return OrganReport(
            organ_name=self.name,
            status=StepStatus.OK,
            payload={
                "consolidated_count": len(result["stored_fact_ids"]) + len(result["corroborated_fact_ids"]),
                "details": result,
            },
            confidence=0.95,
            deterministic=True,
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
        )
