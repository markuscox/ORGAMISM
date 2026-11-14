"""Executive organ: deterministic control flow deciding act, wait, defer, or fail-safe."""

from __future__ import annotations

import time
from typing import Any

from organism.kernel.contracts import OrganContract, OrganReport, StepStatus


class ExecutiveOrgan(OrganContract):
    name = "executive"
    critical = True

    def execute(self, context: dict[str, Any]) -> OrganReport:
        t0 = time.perf_counter()
        risk = context.get("risk_assessment", {})
        plan = context.get("plan", {})
        approved_by_human = bool(context.get("approved_by_human", False))

        if risk.get("blocked"):
            decision = "ABORT_SAFE"
            target_outcome = "FAILED_SAFE"
            rationale = str(risk.get("reason", "Safety policy blocked operation"))
        elif plan.get("requires_human_approval") and not approved_by_human:
            decision = "WAIT_APPROVAL"
            target_outcome = "WAITING"
            rationale = "High-impact operation requires explicit human authorization"
        elif not risk.get("budget_ok", True):
            decision = "DEFER_QUOTA"
            target_outcome = "DEFERRED"
            rationale = str(risk.get("budget_reason", "Token/request budget exhausted"))
        elif plan.get("estimated_tokens", 0) == 0:
            decision = "ACT_DETERMINISTIC"
            target_outcome = "COMPLETED"
            rationale = "Task solvable deterministically at zero token cost"
        else:
            decision = "ACT_WITH_LLM"
            target_outcome = "COMPLETED"
            rationale = "Permitted and within token budget for bounded model synthesis"

        return OrganReport(
            organ_name=self.name,
            status=StepStatus.OK,
            payload={
                "decision": decision,
                "target_outcome": target_outcome,
                "rationale": rationale,
            },
            confidence=1.0,
            deterministic=True,
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
        )
