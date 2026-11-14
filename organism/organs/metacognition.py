"""Metacognition organ: monitors confidence, prediction error, organ health, and unknown bounds."""

from __future__ import annotations

import time
from typing import Any

from organism.kernel.contracts import OrganContract, OrganReport, StepStatus


class MetacognitionOrgan(OrganContract):
    name = "metacognition"
    critical = False

    def execute(self, context: dict[str, Any]) -> OrganReport:
        t0 = time.perf_counter()
        prior = dict(context.get("prior_metacognition", {}))
        comparison = context.get("comparison", {})
        reasoning_report = context.get("reasoning_report", {})
        degraded_organs = list(context.get("degraded_organs", []))

        total_preds = int(prior.get("total_predictions", 0)) + 1
        accurate_preds = int(prior.get("accurate_predictions", 0)) + (
            1 if comparison.get("matched_prediction", True) else 0
        )
        calibration = round(accurate_preds / max(1, total_preds), 4)
        organ_failures = int(prior.get("organ_failures", 0)) + len(degraded_organs)

        confidence = float(reasoning_report.get("confidence", 0.5))
        epistemic_type = reasoning_report.get("epistemic_type", "unknown")
        knowledge_gap = epistemic_type == "unknown" or confidence < 0.45

        updated = {
            "total_predictions": total_preds,
            "accurate_predictions": accurate_preds,
            "calibration_score": calibration,
            "organ_failures": organ_failures,
            "repeated_mistakes": int(prior.get("repeated_mistakes", 0)),
            "last_confidence": confidence,
            "last_prediction_error": float(comparison.get("prediction_error", 0.0)),
            "knowledge_gap_detected": knowledge_gap,
            "degraded_organs_in_cycle": degraded_organs,
        }

        return OrganReport(
            organ_name=self.name,
            status=StepStatus.OK,
            payload=updated,
            confidence=0.95,
            deterministic=True,
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
        )
