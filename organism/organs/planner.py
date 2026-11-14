"""Planning organ: decomposes goals into measurable steps, assumptions, and failure points."""

from __future__ import annotations

import time
from typing import Any

from organism.kernel.contracts import OrganContract, OrganReport, StepStatus


class PlannerOrgan(OrganContract):
    name = "planner"
    critical = False

    def execute(self, context: dict[str, Any]) -> OrganReport:
        t0 = time.perf_counter()
        perception = context.get("perception", {})
        intent = perception.get("detected_intent", "analysis")
        screening = perception.get("screening", {})
        mode = str(context.get("mode", "auto"))

        if intent == "math_computation":
            steps = [
                "Parse numeric expression via AST whitelist",
                "Verify zero arbitrary code execution",
                "Compare exact result against prediction",
            ]
            assumptions = ["Input follows standard arithmetic syntax"]
            failure_points = ["Division by zero", "Unsupported function symbol"]
            est_tokens = 0
        elif intent == "knowledge_assertion":
            steps = [
                "Extract subject-predicate-object triple",
                "Check active semantic graph for contradictions",
                "Stage epistemic assertion with provenance",
            ]
            assumptions = ["Source trust level accurately reflects reliability"]
            failure_points = ["Ambiguous entity boundary", "Conflicting prior fact"]
            est_tokens = 0
        elif mode == "deterministic_only" or intent in {"memory_query", "hypothesis_evaluation"}:
            steps = [
                "Query bounded SQLite episodic and semantic stores",
                "Classify epistemic status without fabricating facts",
                "Record provenance checkpoint",
            ]
            assumptions = ["Relevant records exist in local store or remain unknown"]
            failure_points = ["Missing prior context"]
            est_tokens = 0
        else:
            steps = [
                "Compile compact token-budgeted context",
                "Verify daily and per-cycle token quotas",
                "Execute bounded model synthesis and label output as hypothesis",
            ]
            assumptions = ["Gemini API credentials and free-tier quota are available"]
            failure_points = ["Rate limit 429", "Missing credentials", "Low confidence output"]
            est_tokens = 600

        requires_approval = bool(screening.get("high_impact_requested", False))

        return OrganReport(
            organ_name=self.name,
            status=StepStatus.OK,
            payload={
                "intent": intent,
                "steps": steps,
                "assumptions": assumptions,
                "failure_points": failure_points,
                "estimated_tokens": est_tokens,
                "requires_human_approval": requires_approval,
                "completion_condition": "Explicit terminal status recorded with integrity-verified checkpoint",
            },
            confidence=0.9,
            deterministic=True,
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
        )
