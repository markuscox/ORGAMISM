"""Genuine Metacognition organ: Brier score calibration, 4-axis confidence, organ tracking, and abstention."""

from __future__ import annotations

import time
from typing import Any

from organism.kernel.contracts import OrganContract, OrganReport, StepStatus
from organism.memory.storage import SQLiteMemoryStore


class MetacognitionOrgan(OrganContract):
    name = "metacognition"
    critical = False

    def __init__(self, store: SQLiteMemoryStore | None = None) -> None:
        self._store = store

    def execute(self, context: dict[str, Any]) -> OrganReport:
        t0 = time.perf_counter()
        prior = dict(context.get("prior_metacognition", {}))
        comparison = context.get("comparison", {})
        prediction = context.get("prediction", {})
        perception = context.get("perception", {})
        retrieved_memories = list(context.get("retrieved_memories", []))
        reasoning_report = context.get("reasoning_report", {})
        degraded_organs = list(context.get("degraded_organs", []))
        tokens_used = int(context.get("tokens_used", 0))

        # 1. Prediction accuracy & rolling Brier score calibration
        if self._store is not None:
            history = self._store.list_prediction_history(limit=50)
        else:
            history = []

        if history:
            total_preds = len(history)
            accurate_preds = sum(int(h["matched"]) for h in history)
            brier_score = round(
                sum(float(h["brier_term"]) for h in history) / total_preds,
                4,
            )
            calibration_accuracy = round(accurate_preds / total_preds, 4)
        else:
            total_preds = int(prior.get("total_predictions", 0)) + 1
            accurate_preds = int(prior.get("accurate_predictions", 0)) + (
                1 if comparison.get("matched_prediction", True) else 0
            )
            brier_score = round(float(comparison.get("brier_term", 0.0)), 4)
            calibration_accuracy = round(accurate_preds / max(1, total_preds), 4)

        # 2. Separate the four distinct confidence axes
        pred_conf = round(float(prediction.get("predicted_probability", 0.5)), 4)
        source_conf = round(float(perception.get("reliability", 0.5)), 4)
        if retrieved_memories:
            mem_confs = [float(m.get("confidence", 0.5)) for m in retrieved_memories]
            memory_conf = round(sum(mem_confs) / len(mem_confs), 4)
        else:
            memory_conf = 0.0
        reasoning_conf = round(float(reasoning_report.get("confidence", 0.5)), 4)

        confidence_axes = {
            "prediction_confidence": pred_conf,
            "source_confidence": source_conf,
            "memory_confidence": memory_conf,
            "reasoning_confidence": reasoning_conf,
        }

        # 3. Recurring errors & organ reliability monitoring
        organ_failures = int(prior.get("organ_failures", 0)) + len(degraded_organs)
        repeated_mistakes = int(prior.get("repeated_mistakes", 0)) + (
            1 if not comparison.get("matched_prediction", True) and len(history) >= 2 and not history[0]["matched"] else 0
        )

        organ_health = self._store.list_organ_metrics() if self._store is not None else []
        unhealthy_organs = [o["organ_name"] for o in organ_health if float(o["reliability_ema"]) < 0.7]

        # 4. Epistemic uncertainty & explicit abstention (when to refrain from concluding)
        epistemic_type = reasoning_report.get("epistemic_type", "unknown")
        is_untrusted = bool(perception.get("is_untrusted_data", False))
        intent = perception.get("detected_intent", "analysis")

        refrain_reasons: list[str] = []
        if epistemic_type == "unknown" and reasoning_conf < 0.55 and intent not in {"memory_query"}:
            refrain_reasons.append("insufficient_evidence_or_unknown_domain")
        if intent == "memory_query" and not retrieved_memories:
            refrain_reasons.append("no_supporting_memory_records")
        if is_untrusted and memory_conf < 0.6 and reasoning_conf < 0.65:
            refrain_reasons.append("uncorroborated_untrusted_source")
        if total_preds >= 5 and brier_score > 0.35 and pred_conf < 0.6:
            refrain_reasons.append("high_predictive_calibration_drift")
        if len(degraded_organs) >= 2:
            refrain_reasons.append("multiple_degraded_organs_in_cycle")

        refrain_recommended = len(refrain_reasons) > 0
        knowledge_gap = epistemic_type == "unknown" or reasoning_conf < 0.5 or refrain_recommended

        updated = {
            "total_predictions": total_preds,
            "accurate_predictions": accurate_preds,
            "calibration_score": calibration_accuracy,
            "brier_score": brier_score,
            "confidence_axes": confidence_axes,
            "organ_failures": organ_failures,
            "repeated_mistakes": repeated_mistakes,
            "unhealthy_organs": unhealthy_organs,
            "last_confidence": reasoning_conf,
            "last_prediction_error": float(comparison.get("prediction_error", 0.0)),
            "tokens_consumed_cycle": tokens_used,
            "knowledge_gap_detected": knowledge_gap,
            "refrain_recommended": refrain_recommended,
            "refrain_reasons": refrain_reasons,
            "degraded_organs_in_cycle": degraded_organs,
        }

        return OrganReport(
            organ_name=self.name,
            status=StepStatus.OK,
            payload=updated,
            confidence=round(max(0.2, 1.0 - brier_score), 4),
            deterministic=True,
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
        )
