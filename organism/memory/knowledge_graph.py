"""Graphiti-inspired temporal knowledge graph with evidence-based lifecycle and poisoning resistance."""

from __future__ import annotations

import math
from typing import Any

from organism.kernel.contracts import EpistemicType, MemoryStatus, TrustLevel
from .storage import SQLiteMemoryStore


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-12.0, min(12.0, x))))


class TemporalKnowledgeGraph:
    """
    Manages temporal assertions, independent evidence pooling, contradiction invalidation,
    and resistance to single-source memory poisoning.
    """

    def __init__(
        self,
        store: SQLiteMemoryStore,
        verify_threshold: float = 0.78,
        min_independent_sources: int = 2,
    ) -> None:
        self._store = store
        self.verify_threshold = verify_threshold
        self.min_independent_sources = min_independent_sources

    @staticmethod
    def _source_weight(trust_level: str, deterministic_proof: bool = False) -> float:
        if deterministic_proof:
            return 2.4
        if trust_level == TrustLevel.TRUSTED_OPERATOR.value:
            return 0.85
        if trust_level == TrustLevel.INTERNAL_SYSTEM.value:
            return 0.75
        return 0.25  # untrusted_external carries low prior weight

    def _recompute_fact_state(
        self, fact: dict[str, Any], evidence_list: list[dict[str, Any]]
    ) -> tuple[float, MemoryStatus]:
        # Pool evidence in log-odds space using unique sources for support to prevent single-source spam
        support_by_source: dict[str, float] = {}
        contradict_weight = 0.0
        has_deterministic_proof = False

        for ev in evidence_list:
            if ev["stance"] == "support":
                src = ev["source"]
                support_by_source[src] = max(support_by_source.get(src, 0.0), float(ev["weight"]))
                if float(ev["weight"]) >= 2.0:
                    has_deterministic_proof = True
            else:
                contradict_weight += float(ev["weight"])

        support_sum = sum(support_by_source.values())
        net_log_odds = -0.25 + support_sum - contradict_weight
        conf = round(_sigmoid(net_log_odds), 4)
        independent_count = len(support_by_source)
        ep_type = fact["epistemic_type"]

        if contradict_weight > support_sum + 0.2:
            return conf, MemoryStatus.REJECTED

        if has_deterministic_proof:
            return max(0.92, conf), MemoryStatus.VERIFIED

        # Never silently transform a hypothesis into a verified fact
        if ep_type == EpistemicType.HYPOTHESIS.value:
            status = (
                MemoryStatus.EVIDENCE_CHECKED
                if len(evidence_list) >= 2
                else MemoryStatus.CANDIDATE
            )
            return min(0.75, conf), status

        if (
            independent_count >= self.min_independent_sources
            and conf >= self.verify_threshold
            and ep_type == EpistemicType.FACT.value
        ):
            return conf, MemoryStatus.VERIFIED

        non_zero_evidence = [e for e in evidence_list if float(e.get("weight", 0.0)) > 0.0]
        if len(non_zero_evidence) >= 2 or independent_count >= 2:
            return conf, MemoryStatus.EVIDENCE_CHECKED

        # Single observation from ANY source (including trusted_operator) remains CANDIDATE
        return min(0.65, conf), MemoryStatus.CANDIDATE

    def record_assertion(
        self,
        subject: str,
        predicate: str,
        object_value: str,
        epistemic_type: EpistemicType,
        confidence: float,
        source_episode_id: str,
        status: MemoryStatus = MemoryStatus.CANDIDATE,
        source: str = "kernel",
        trust_level: str = TrustLevel.INTERNAL_SYSTEM.value,
        deterministic_proof: bool = False,
    ) -> dict[str, Any]:
        subject_norm = subject.strip().lower()
        predicate_norm = predicate.strip().lower()
        value_norm = object_value.strip()
        weight = self._source_weight(trust_level, deterministic_proof=deterministic_proof)

        # 1. Check if identical active triple already exists -> add corroborating evidence!
        existing_same = self._store.find_semantic_triple(subject_norm, predicate_norm, value_norm)
        if existing_same is not None:
            prior_ev = self._store.list_evidence_for_fact(existing_same["fact_id"])
            duplicate_same_source = any(
                e["source"] == source and e["stance"] == "support" for e in prior_ev
            )
            self._store.insert_evidence_record(
                fact_id=existing_same["fact_id"],
                episode_id=source_episode_id,
                source=source,
                trust_level=trust_level,
                stance="support",
                weight=0.0 if duplicate_same_source else weight,
                rationale=(
                    "Duplicate observation from identical source (zero independent weight)"
                    if duplicate_same_source
                    else "Independent corroborating observation"
                ),
            )
            updated_ev = self._store.list_evidence_for_fact(existing_same["fact_id"])
            new_conf, new_status = self._recompute_fact_state(existing_same, updated_ev)
            self._store.update_semantic_fact_lifecycle(
                existing_same["fact_id"],
                status=new_status,
                confidence=new_conf,
                evidence_delta=0 if duplicate_same_source else 1,
            )
            return {
                "fact_id": existing_same["fact_id"],
                "edge_id": None,
                "lifecycle_status": new_status.value,
                "confidence": new_conf,
                "corroborated": not duplicate_same_source,
                "duplicate_source_blocked": duplicate_same_source,
                "contradictions_detected": [],
                "invalidated_fact_ids": [],
            }

        # 2. Check for contradicting assertions on (subject, predicate)
        active_facts = self._store.list_semantic_facts(include_invalidated=False, limit=250)
        contradictions: list[str] = []
        verified_conflict = False
        for existing in active_facts:
            if (
                existing["subject"].lower() == subject_norm
                and existing["predicate"].lower() == predicate_norm
                and existing["object_value"].lower() != value_norm.lower()
                and existing["status"] != MemoryStatus.REJECTED.value
            ):
                contradictions.append(existing["fact_id"])
                if existing["status"] == MemoryStatus.VERIFIED.value:
                    verified_conflict = True

        # Poisoning defense: untrusted external source contradicting a VERIFIED fact is REJECTED immediately
        if verified_conflict and trust_level == TrustLevel.UNTRUSTED_EXTERNAL.value:
            rejected_id = self._store.insert_semantic_fact(
                subject=subject_norm,
                predicate=predicate_norm,
                object_value=value_norm,
                epistemic_type=EpistemicType.HYPOTHESIS,
                confidence=0.18,
                status=MemoryStatus.REJECTED,
                source_episode_id=source_episode_id,
            )
            self._store.insert_evidence_record(
                fact_id=rejected_id,
                episode_id=source_episode_id,
                source=source,
                trust_level=trust_level,
                stance="contradict",
                weight=1.5,
                rationale="Rejected: untrusted claim contradicts verified semantic fact",
            )
            for verified_id in contradictions:
                self._store.update_semantic_fact_lifecycle(verified_id, contradiction_delta=1)
            return {
                "fact_id": rejected_id,
                "edge_id": None,
                "lifecycle_status": MemoryStatus.REJECTED.value,
                "confidence": 0.18,
                "corroborated": False,
                "duplicate_source_blocked": False,
                "contradictions_detected": contradictions,
                "invalidated_fact_ids": [],
            }

        # 3. Create new record starting at CANDIDATE (unless deterministic_proof)
        initial_status = MemoryStatus.VERIFIED if deterministic_proof else MemoryStatus.CANDIDATE
        initial_conf = (
            max(0.92, confidence)
            if deterministic_proof
            else min(0.62, max(0.30, _sigmoid(-0.25 + weight)))
        )

        new_fact_id = self._store.insert_semantic_fact(
            subject=subject_norm,
            predicate=predicate_norm,
            object_value=value_norm,
            epistemic_type=epistemic_type,
            confidence=round(initial_conf, 4),
            status=initial_status,
            source_episode_id=source_episode_id,
        )
        self._store.insert_evidence_record(
            fact_id=new_fact_id,
            episode_id=source_episode_id,
            source=source,
            trust_level=trust_level,
            stance="support",
            weight=weight,
            rationale="Initial observation registered in evidence ledger",
        )

        # Record contradiction evidence & supersede unverified/older values on trusted updates
        invalidated_ids: list[str] = []
        if contradictions and trust_level != TrustLevel.UNTRUSTED_EXTERNAL.value and epistemic_type == EpistemicType.FACT:
            for old_id in contradictions:
                self._store.insert_evidence_record(
                    fact_id=old_id,
                    episode_id=source_episode_id,
                    source=source,
                    trust_level=trust_level,
                    stance="contradict",
                    weight=weight,
                    rationale=f"Contradicted by newer observation {new_fact_id} ({value_norm})",
                )
                self._store.update_semantic_fact_lifecycle(old_id, contradiction_delta=1)
                self._store.invalidate_semantic_fact(old_id, superseded_by=new_fact_id)
                invalidated_ids.append(old_id)

        edge_id = self._store.insert_kg_edge(
            source_entity=subject_norm,
            relation=predicate_norm,
            target_entity=value_norm,
            episode_id=source_episode_id,
            confidence=round(initial_conf, 4),
        )

        return {
            "fact_id": new_fact_id,
            "edge_id": edge_id,
            "lifecycle_status": initial_status.value,
            "confidence": round(initial_conf, 4),
            "corroborated": False,
            "duplicate_source_blocked": False,
            "contradictions_detected": contradictions,
            "invalidated_fact_ids": invalidated_ids,
        }
