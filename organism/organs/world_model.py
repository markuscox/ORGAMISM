"""World-model organ: symbolic state-transition prediction and outcome comparison."""

from __future__ import annotations

import time
from typing import Any

from organism.kernel.contracts import OrganContract, OrganReport, StepStatus


class WorldModelOrgan(OrganContract):
    name = "world_model"
    critical = False

    def execute(self, context: dict[str, Any]) -> OrganReport:
        t0 = time.perf_counter()
        phase = context.get("phase", "predict")

        if phase == "compare":
            prediction = context.get("prediction", {})
            observed = context.get("observed", {})
            expected_status = prediction.get("expected_status", "ok")
            actual_status = observed.get("status", "ok")
            expected_det = bool(prediction.get("expected_deterministic", True))
            actual_det = bool(observed.get("deterministic", True))

            matched = (expected_status == actual_status) and (expected_det == actual_det)
            prediction_error = 0.0 if matched else (0.35 if expected_status == actual_status else 0.75)

            return OrganReport(
                organ_name=self.name,
                status=StepStatus.OK,
                payload={
                    "matched_prediction": matched,
                    "prediction_error": prediction_error,
                    "expected_status": expected_status,
                    "actual_status": actual_status,
                    "expected_deterministic": expected_det,
                    "actual_deterministic": actual_det,
                },
                confidence=0.95,
                deterministic=True,
                duration_ms=round((time.perf_counter() - t0) * 1000, 3),
            )

        # Predict phase (Step 8)
        plan = context.get("plan", {})
        perception = context.get("perception", {})
        screening = perception.get("screening", {})

        if screening.get("blocked"):
            expected_status = "blocked"
            expected_det = True
            expected_effect = "Blocked by safety boundary prior to execution"
        elif plan.get("requires_human_approval"):
            expected_status = "waiting"
            expected_det = True
            expected_effect = "Pause cycle in WAITING until human approval"
        elif plan.get("estimated_tokens", 0) == 0:
            expected_status = "ok"
            expected_det = True
            expected_effect = "Resolve deterministically with zero token cost"
        else:
            expected_status = "ok"
            expected_det = False
            expected_effect = "Synthesize response within token budget"

        return OrganReport(
            organ_name=self.name,
            status=StepStatus.OK,
            payload={
                "expected_status": expected_status,
                "expected_deterministic": expected_det,
                "expected_effect": expected_effect,
                "predicted_token_cost": plan.get("estimated_tokens", 0),
            },
            confidence=0.85,
            deterministic=True,
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
        )
