"""Evidence-based memory consolidation, deduplication, and controlled selective forgetting."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from organism.kernel.contracts import EpistemicType, MemoryStatus, TrustLevel
from .knowledge_graph import TemporalKnowledgeGraph
from .retrieval import compute_actr_activation
from .storage import SQLiteMemoryStore


class MemoryConsolidator:
    """
    Stages candidate assertions through:
      OBSERVED -> CANDIDATE -> EVIDENCE_CHECKED -> VERIFIED | REJECTED
    and executes controlled selective forgetting on low-activation stale clutter.
    """

    def __init__(
        self,
        store: SQLiteMemoryStore,
        kg: TemporalKnowledgeGraph,
        decay_rate: float = 0.5,
        max_candidate_retention: int = 40,
    ) -> None:
        self._store = store
        self._kg = kg
        self.decay_rate = decay_rate
        self.max_candidate_retention = max_candidate_retention

    def consolidate_candidates(
        self, candidates: list[dict[str, Any]], episode_id: str
    ) -> dict[str, Any]:
        stored_facts: list[str] = []
        corroborated_facts: list[str] = []
        rejected_facts: list[str] = []
        contradictions: list[str] = []
        invalidated: list[str] = []
        lifecycle_transitions: list[dict[str, Any]] = []

        for cand in candidates:
            subject = str(cand.get("subject", "")).strip()
            predicate = str(cand.get("predicate", "")).strip()
            obj = str(cand.get("object_value", "")).strip()
            if not subject or not predicate or not obj:
                continue

            ep_type = EpistemicType(cand.get("epistemic_type", EpistemicType.HYPOTHESIS.value))
            confidence = float(cand.get("confidence", 0.55))
            source = str(cand.get("source", "kernel"))
            trust_level = str(cand.get("trust_level", TrustLevel.INTERNAL_SYSTEM.value))
            deterministic_proof = bool(cand.get("deterministic_proof", False))

            res = self._kg.record_assertion(
                subject=subject,
                predicate=predicate,
                object_value=obj,
                epistemic_type=ep_type,
                confidence=confidence,
                source_episode_id=episode_id,
                status=MemoryStatus.CANDIDATE,
                source=source,
                trust_level=trust_level,
                deterministic_proof=deterministic_proof,
            )

            status_out = res["lifecycle_status"]
            if status_out == MemoryStatus.REJECTED.value:
                rejected_facts.append(res["fact_id"])
            elif res.get("corroborated"):
                corroborated_facts.append(res["fact_id"])
            else:
                stored_facts.append(res["fact_id"])

            contradictions.extend(res["contradictions_detected"])
            invalidated.extend(res["invalidated_fact_ids"])
            lifecycle_transitions.append(
                {
                    "fact_id": res["fact_id"],
                    "status": status_out,
                    "confidence": res["confidence"],
                    "duplicate_source_blocked": res.get("duplicate_source_blocked", False),
                }
            )

        return {
            "stored_fact_ids": stored_facts,
            "corroborated_fact_ids": corroborated_facts,
            "rejected_fact_ids": rejected_facts,
            "contradictions_detected": contradictions,
            "invalidated_fact_ids": invalidated,
            "lifecycle_transitions": lifecycle_transitions,
        }

    def run_controlled_forgetting(self, max_retain: int | None = None) -> dict[str, Any]:
        """
        Controlled forgetting: archives stale REJECTED or low-activation CANDIDATE entries
        when unverified memory exceeds retention budget. Never deletes VERIFIED facts or episodes.
        """
        limit = max_retain if max_retain is not None else self.max_candidate_retention
        facts = self._store.list_semantic_facts(include_invalidated=False, include_forgotten=False, limit=300)
        now = datetime.now(timezone.utc)

        unverified = [
            f
            for f in facts
            if f["status"] in {MemoryStatus.CANDIDATE.value, MemoryStatus.OBSERVED.value, MemoryStatus.REJECTED.value}
        ]
        if len(unverified) <= limit:
            return {"forgotten_count": 0, "forgotten_ids": []}

        scored: list[tuple[float, dict[str, Any]]] = []
        for f in unverified:
            activation = compute_actr_activation(
                int(f.get("access_count", 1)),
                f.get("last_accessed_at") or f.get("valid_from"),
                decay_rate=self.decay_rate,
                now=now,
            )
            priority = activation + (0.25 if f["status"] != MemoryStatus.REJECTED.value else -0.4) + 0.3 * float(f["confidence"])
            scored.append((priority, f))

        scored.sort(key=lambda pair: pair[0])
        to_forget = scored[: len(unverified) - limit]
        forgotten_ids: list[str] = []
        for _, fact in to_forget:
            self._store.mark_fact_forgotten(fact["fact_id"])
            forgotten_ids.append(fact["fact_id"])

        return {"forgotten_count": len(forgotten_ids), "forgotten_ids": forgotten_ids}
