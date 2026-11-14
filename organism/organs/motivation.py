"""Motivation & homeostasis organ: bounded operational control variables (not simulated emotions)."""

from __future__ import annotations

import time
from typing import Any

from organism.kernel.contracts import OrganContract, OrganReport, StepStatus


def _clamp(val: float) -> float:
    return round(max(0.0, min(1.0, val)), 4)


class MotivationOrgan(OrganContract):
    name = "motivation"
    critical = False

    def execute(self, context: dict[str, Any]) -> OrganReport:
        t0 = time.perf_counter()
        prior = dict(context.get("prior_homeostasis", {}))
        budget_totals = context.get("budget_totals", {})
        active_goals = list(context.get("active_goals", []))

        remaining_ratio = (
            budget_totals.get("remaining_tokens", 200000)
            / max(1, budget_totals.get("daily_token_limit", 200000))
        )

        uncertainty_pressure = _clamp(float(prior.get("uncertainty_pressure", 0.25)))
        consistency_pressure = _clamp(float(prior.get("consistency_pressure", 0.15)))
        goal_completion_drive = _clamp(0.4 + 0.1 * min(len(active_goals), 5))
        resource_conservation_drive = _clamp(1.0 - 0.5 * remaining_ratio)

        state = {
            "uncertainty_pressure": uncertainty_pressure,
            "consistency_pressure": consistency_pressure,
            "goal_completion_drive": goal_completion_drive,
            "resource_conservation_drive": resource_conservation_drive,
        }

        constraints = [
            "Prefer deterministic resolution when available",
            "Remain within daily token and request budgets",
            "Do not alter security policies or self-grant permissions",
        ]

        return OrganReport(
            organ_name=self.name,
            status=StepStatus.OK,
            payload={
                "active_goals": active_goals,
                "homeostasis": state,
                "constraints": constraints,
            },
            confidence=1.0,
            deterministic=True,
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
        )
