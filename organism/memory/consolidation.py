"""Memory consolidation helpers for episodic-to-semantic staging and deduplication."""

from __future__ import annotations

from typing import Any

from organism.kernel.contracts import EpistemicType, MemoryStatus
from .knowledge_graph import TemporalKnowledgeGraph
from .storage import SQLiteMemoryStore


class MemoryConsolidator:
    """Converts verified cycle observations into structured semantic records."""

    def __init__(self, store: SQLiteMemoryStore, kg: TemporalKnowledgeGraph) -> None:
        self._store = store
        self._kg = kg

    def consolidate_candidates(
        self, candidates: list[dict[str, Any]], episode_id: str
    ) -> dict[str, Any]:
        stored_facts: list[str] = []
        contradictions: list[str] = []
        invalidated: list[str] = []

        existing_active = self._store.list_semantic_facts(include_invalidated=False, limit=200)
        seen_triples = {
            (f["subject"].lower(), f["predicate"].lower(), f["object_value"].lower())
            for f in existing_active
        }

        for cand in candidates:
            subject = str(cand.get("subject", "")).strip()
            predicate = str(cand.get("predicate", "")).strip()
            obj = str(cand.get("object_value", "")).strip()
            if not subject or not predicate or not obj:
                continue

            triple = (subject.lower(), predicate.lower(), obj.lower())
            if triple in seen_triples:
                continue  # Deduplicate identical active knowledge

            ep_type = EpistemicType(cand.get("epistemic_type", EpistemicType.HYPOTHESIS.value))
            confidence = float(cand.get("confidence", 0.6))
            status = MemoryStatus(cand.get("status", MemoryStatus.CANDIDATE.value))

            res = self._kg.record_assertion(
                subject=subject,
                predicate=predicate,
                object_value=obj,
                epistemic_type=ep_type,
                confidence=confidence,
                source_episode_id=episode_id,
                status=status,
            )
            stored_facts.append(res["fact_id"])
            contradictions.extend(res["contradictions_detected"])
            invalidated.extend(res["invalidated_fact_ids"])
            seen_triples.add(triple)

        return {
            "stored_fact_ids": stored_facts,
            "contradictions_detected": contradictions,
            "invalidated_fact_ids": invalidated,
        }
