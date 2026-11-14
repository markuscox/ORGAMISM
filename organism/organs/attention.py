"""Attention organ: salience scoring to select what enters the Global Cognitive Workspace."""

from __future__ import annotations

import time
from typing import Any

from organism.kernel.contracts import OrganContract, OrganReport, StepStatus


class AttentionOrgan(OrganContract):
    name = "attention"
    critical = False

    def execute(self, context: dict[str, Any]) -> OrganReport:
        t0 = time.perf_counter()
        perception: dict[str, Any] = context.get("perception", {})
        memories: list[dict[str, Any]] = context.get("retrieved_memories", [])
        goals: list[str] = context.get("active_goals", [])

        goal_tokens = set(" ".join(goals).lower().split())
        scored: list[dict[str, Any]] = []

        # Score the incoming perception first
        stimulus_text = str(perception.get("normalized_text", ""))
        stimulus_tokens = set(stimulus_text.lower().split())
        goal_overlap = len(goal_tokens & stimulus_tokens) / max(1, len(goal_tokens))
        urgency = 0.9 if perception.get("screening", {}).get("high_impact_requested") else 0.55
        novelty = 0.85 if not memories else 0.65
        salience = round(min(1.0, 0.35 + 0.3 * urgency + 0.2 * novelty + 0.15 * goal_overlap), 4)

        scored.append(
            {
                "item_id": "current_stimulus",
                "layer": "perception",
                "summary": stimulus_text[:240],
                "epistemic_type": perception.get("epistemic_hint", "unknown"),
                "salience": salience,
                "source": perception.get("source", "unknown"),
            }
        )

        # Score retrieved memories by relevance, epistemic reliability, and novelty
        for idx, mem in enumerate(memories):
            base_score = float(mem.get("score", 0.3))
            mem_salience = round(min(1.0, 0.55 * base_score + 0.25 * (1.0 / (idx + 1))), 4)
            scored.append(
                {
                    "item_id": mem.get("id", f"mem_{idx}"),
                    "layer": mem.get("layer", "memory"),
                    "summary": str(mem.get("summary", ""))[:220],
                    "epistemic_type": mem.get("epistemic_type", "unknown"),
                    "salience": mem_salience,
                    "source": mem.get("source", "memory"),
                }
            )

        scored.sort(key=lambda x: x["salience"], reverse=True)
        return OrganReport(
            organ_name=self.name,
            status=StepStatus.OK,
            payload={"ranked_items": scored, "selected_count": len(scored)},
            confidence=0.9,
            deterministic=True,
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
        )
