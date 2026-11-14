"""Lightweight Graphiti-inspired temporal knowledge graph backed by SQLite."""

from __future__ import annotations

from typing import Any

from organism.kernel.contracts import EpistemicType, MemoryStatus
from .storage import SQLiteMemoryStore


class TemporalKnowledgeGraph:
    """Manages temporal facts, provenance edges, and contradiction invalidation."""

    def __init__(self, store: SQLiteMemoryStore) -> None:
        self._store = store

    def record_assertion(
        self,
        subject: str,
        predicate: str,
        object_value: str,
        epistemic_type: EpistemicType,
        confidence: float,
        source_episode_id: str,
        status: MemoryStatus = MemoryStatus.VERIFIED,
    ) -> dict[str, Any]:
        subject_norm = subject.strip().lower()
        predicate_norm = predicate.strip().lower()
        value_norm = object_value.strip()

        active_facts = self._store.list_semantic_facts(include_invalidated=False, limit=200)
        contradictions: list[str] = []

        # Detect conflicts on same (subject, predicate) with different value
        for existing in active_facts:
            if (
                existing["subject"].lower() == subject_norm
                and existing["predicate"].lower() == predicate_norm
                and existing["object_value"].lower() != value_norm.lower()
            ):
                contradictions.append(existing["fact_id"])

        new_fact_id = self._store.insert_semantic_fact(
            subject=subject_norm,
            predicate=predicate_norm,
            object_value=value_norm,
            epistemic_type=epistemic_type,
            confidence=confidence,
            status=status,
            source_episode_id=source_episode_id,
        )

        # Only verified facts invalidate prior contradicting verified facts;
        # hypotheses/predictions are recorded alongside without erasing established facts.
        invalidated_ids: list[str] = []
        if epistemic_type == EpistemicType.FACT and status in {MemoryStatus.VERIFIED, MemoryStatus.ACTIVE}:
            for old_id in contradictions:
                self._store.invalidate_semantic_fact(old_id, superseded_by=new_fact_id)
                invalidated_ids.append(old_id)

        edge_id = self._store.insert_kg_edge(
            source_entity=subject_norm,
            relation=predicate_norm,
            target_entity=value_norm,
            episode_id=source_episode_id,
            confidence=confidence,
        )

        return {
            "fact_id": new_fact_id,
            "edge_id": edge_id,
            "contradictions_detected": contradictions,
            "invalidated_fact_ids": invalidated_ids,
        }
