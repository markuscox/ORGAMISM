"""Active Learning & Curiosity organ: Shannon entropy, Expected Information Gain (EIG), and safe bounded probes."""

from __future__ import annotations

import math
import time
from typing import Any

from organism.kernel.contracts import MemoryStatus, OrganContract, OrganReport, StepStatus, TrustLevel
from organism.memory.knowledge_graph import TemporalKnowledgeGraph
from organism.memory.storage import SQLiteMemoryStore


def binary_entropy(p: float) -> float:
    p_clamped = max(1e-6, min(1.0 - 1e-6, p))
    return -(p_clamped * math.log2(p_clamped) + (1.0 - p_clamped) * math.log2(1.0 - p_clamped))


class ActiveLearningOrgan(OrganContract):
    """Identifies epistemic gaps, estimates Expected Value of Information (EVI), and runs safe internal probes."""

    name = "active_learning"
    critical = False

    def __init__(self, store: SQLiteMemoryStore, kg: TemporalKnowledgeGraph | None = None) -> None:
        self._store = store
        self._kg = kg or TemporalKnowledgeGraph(store)

    def execute(self, context: dict[str, Any]) -> OrganReport:
        t0 = time.perf_counter()
        proposals: list[dict[str, Any]] = []

        # 1. Inspect unverified CANDIDATE / EVIDENCE_CHECKED semantic records (highest entropy near p=0.5)
        facts = self._store.list_semantic_facts(
            include_invalidated=False, include_forgotten=False, limit=100
        )
        for fact in facts:
            if fact["status"] in {"candidate", "evidence_checked", "observed"}:
                p = float(fact["confidence"])
                h_before = binary_entropy(p)
                p_after_pos = min(0.95, p + 0.25)
                p_after_neg = max(0.05, p - 0.25)
                h_after = 0.5 * binary_entropy(p_after_pos) + 0.5 * binary_entropy(p_after_neg)
                eig = round(max(0.0, h_before - h_after), 4)
                cost = 0.08  # Low deterministic verification cost (0 LLM tokens)
                evi = round(eig - cost, 4)

                if eig >= 0.05:
                    target_key = f"fact:{fact['subject']}:{fact['predicate']}"
                    probe = (
                        f"Cross-check episodic provenance and request independent corroboration for "
                        f"'{fact['subject']} {fact['predicate']} {fact['object_value']}'"
                    )
                    exp_id = self._store.upsert_active_experiment(
                        target_fact_id=fact["fact_id"],
                        target_key=target_key,
                        hypothesis=f"{fact['subject']} {fact['predicate']} {fact['object_value']}",
                        uncertainty_entropy=round(h_before, 4),
                        expected_info_gain=eig,
                        estimated_cost=cost,
                        evi_score=evi,
                        proposed_probe=probe,
                    )
                    proposals.append(
                        {
                            "experiment_id": exp_id,
                            "target_key": target_key,
                            "entropy": round(h_before, 4),
                            "eig": eig,
                            "cost": cost,
                            "evi": evi,
                            "probe": probe,
                        }
                    )

        # 2. Inspect high-uncertainty World Model transitions
        for tr in self._store.list_world_transitions(limit=30):
            alpha = dict(tr["alpha_counts"])
            total = sum(alpha.values())
            if total <= 0:
                continue
            probs = [v / total for v in alpha.values() if v > 0]
            h = -sum(p * math.log2(max(1e-9, p)) for p in probs)
            if tr["sample_count"] < 3 and h > 1.2:
                eig = round(min(0.6, h * 0.22), 4)
                cost = 0.12
                evi = round(eig - cost, 4)
                target_key = f"transition:{tr['state_action_key']}"
                probe = f"Sample controlled internal transition probe for {tr['state_action_key']}"
                exp_id = self._store.upsert_active_experiment(
                    target_fact_id=None,
                    target_key=target_key,
                    hypothesis=f"Transition dynamics for {tr['state_action_key']} stabilize with experience",
                    uncertainty_entropy=round(h, 4),
                    expected_info_gain=eig,
                    estimated_cost=cost,
                    evi_score=evi,
                    proposed_probe=probe,
                )
                proposals.append(
                    {
                        "experiment_id": exp_id,
                        "target_key": target_key,
                        "entropy": round(h, 4),
                        "eig": eig,
                        "cost": cost,
                        "evi": evi,
                        "probe": probe,
                    }
                )

        proposals.sort(key=lambda p: p["evi"], reverse=True)
        return OrganReport(
            organ_name=self.name,
            status=StepStatus.OK,
            payload={
                "proposals_count": len(proposals),
                "top_proposals": proposals[:5],
            },
            confidence=0.95,
            deterministic=True,
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
        )

    def run_safe_experiment(self, experiment_id: str) -> dict[str, Any] | None:
        """Execute a bounded internal experiment (memory/evidence audit) without external side effects."""
        exp = self._store.get_active_experiment(experiment_id)
        if exp is None:
            return None

        h_before = float(exp["uncertainty_entropy"])
        fact_id = exp.get("target_fact_id")

        if fact_id:
            evidence = self._store.list_evidence_for_fact(fact_id)
            episodes = self._store.list_episodes(limit=80)
            support = sum(e["weight"] for e in evidence if e["stance"] == "support")
            contradict = sum(e["weight"] for e in evidence if e["stance"] == "contradict")

            hyp_lower = exp["hypothesis"].lower()
            matching_eps = [
                ep
                for ep in episodes
                if ep["outcome_status"] == "COMPLETED"
                and hyp_lower in (ep["event_content"] + " " + ep["outcome_summary"]).lower()
                and ep["trust_level"] != TrustLevel.UNTRUSTED_EXTERNAL.value
            ]

            if len(matching_eps) >= 2 and contradict == 0:
                distinct_sources = {ep["source"] for ep in matching_eps}
                if len(distinct_sources) >= 2:
                    self._store.update_semantic_fact_lifecycle(
                        fact_id=fact_id,
                        status=MemoryStatus.VERIFIED,
                        confidence=0.84,
                    )
                    h_after = binary_entropy(0.84)
                    result_summary = (
                        f"Evidence audit confirmed {len(distinct_sources)} independent trusted source(s); "
                        "promoted claim to VERIFIED."
                    )
                else:
                    self._store.update_semantic_fact_lifecycle(
                        fact_id=fact_id,
                        status=MemoryStatus.EVIDENCE_CHECKED,
                        confidence=0.72,
                    )
                    h_after = binary_entropy(0.72)
                    result_summary = (
                        f"Evidence audit found {len(matching_eps)} consistent episode(s) from 1 source; "
                        "advanced claim to EVIDENCE_CHECKED (awaiting independent source)."
                    )
            elif contradict > support:
                self._store.update_semantic_fact_lifecycle(
                    fact_id=fact_id,
                    status=MemoryStatus.REJECTED,
                    confidence=0.15,
                )
                h_after = binary_entropy(0.15)
                result_summary = "Evidence audit detected net contradiction; transitioned claim to REJECTED."
            else:
                h_after = min(h_before, binary_entropy(0.66))
                result_summary = (
                    f"Consistency audit clear ({len(matching_eps)} match(es), 0 contradictions); "
                    "retained as CANDIDATE pending independent corroboration."
                )

            realized_gain = round(max(0.01, h_before - h_after), 4)
        else:
            sa_key = exp["target_key"].replace("transition:", "", 1)
            tr = self._store.get_world_transition(sa_key)
            if tr is not None:
                result_summary = (
                    f"Inspected transition {sa_key}: sample_count={tr['sample_count']}, "
                    f"td_error_ema={tr['td_error_ema']}."
                )
            else:
                result_summary = f"Transition {sa_key} has no observations yet."
            realized_gain = 0.05

        self._store.mark_experiment_executed(experiment_id, result_summary, realized_gain)
        return self._store.get_active_experiment(experiment_id)
