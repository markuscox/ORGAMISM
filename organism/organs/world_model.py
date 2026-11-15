"""Adaptive World-Model organ: Bayesian Dirichlet-Beta state-transition learning, TD error, and EWC protection."""

from __future__ import annotations

import math
import time
from typing import Any

from organism.kernel.contracts import OrganContract, OrganReport, StepStatus
from organism.memory.continual import OUTCOME_CLASSES, ContinualLearningManager
from organism.memory.storage import SQLiteMemoryStore


def build_state_key(perception: dict[str, Any], plan: dict[str, Any], memories_count: int) -> str:
    intent = str(perception.get("detected_intent", "analysis"))
    trust = str(perception.get("trust_level", "unknown"))
    blocked = "blocked" if perception.get("screening", {}).get("blocked") else "clear"
    approval = "gated" if plan.get("requires_human_approval") else "open"
    mem_bucket = "has_mem" if memories_count > 0 else "no_mem"
    return f"{intent}:{trust}:{blocked}:{approval}:{mem_bucket}"


def infer_action_key(plan: dict[str, Any], perception: dict[str, Any]) -> str:
    if perception.get("screening", {}).get("blocked"):
        return "ABORT_SAFE"
    if plan.get("requires_human_approval"):
        return "WAIT_APPROVAL"
    if int(plan.get("estimated_tokens", 0)) == 0:
        return "ACT_DETERMINISTIC"
    return "ACT_WITH_LLM"


class WorldModelOrgan(OrganContract):
    """Interpretable statistical transition model learning online from experience."""

    name = "world_model"
    critical = False

    def __init__(
        self,
        store: SQLiteMemoryStore | None = None,
        continual: ContinualLearningManager | None = None,
        learning_rate: float = 0.25,
    ) -> None:
        self._store = store
        self._continual = continual
        self.learning_rate = learning_rate
        # In-memory fallback cache when instantiated standalone without SQLite store
        self._local_transitions: dict[str, dict[str, Any]] = {}

    def _get_transition(self, sa_key: str) -> dict[str, Any] | None:
        if self._store is not None:
            return self._store.get_world_transition(sa_key)
        return self._local_transitions.get(sa_key)

    def _save_transition(
        self,
        sa_key: str,
        state_key: str,
        action_key: str,
        alpha_counts: dict[str, float],
        det_alpha: float,
        det_beta: float,
        td_error_ema: float,
        avg_tokens_ema: float,
        fisher_precision: float,
        anchor_alpha: dict[str, float],
        sample_count: int,
    ) -> None:
        if self._store is not None:
            self._store.upsert_world_transition(
                state_action_key=sa_key,
                state_key=state_key,
                action_key=action_key,
                alpha_counts=alpha_counts,
                det_alpha=det_alpha,
                det_beta=det_beta,
                td_error_ema=td_error_ema,
                avg_tokens_ema=avg_tokens_ema,
                fisher_precision=fisher_precision,
                anchor_alpha=anchor_alpha,
                sample_count=sample_count,
            )
        else:
            self._local_transitions[sa_key] = {
                "state_action_key": sa_key,
                "state_key": state_key,
                "action_key": action_key,
                "alpha_counts": alpha_counts,
                "det_alpha": det_alpha,
                "det_beta": det_beta,
                "td_error_ema": td_error_ema,
                "avg_tokens_ema": avg_tokens_ema,
                "fisher_precision": fisher_precision,
                "anchor_alpha": anchor_alpha,
                "sample_count": sample_count,
            }

    @staticmethod
    def _prior_alpha(perception: dict[str, Any], plan: dict[str, Any]) -> tuple[dict[str, float], float, float]:
        """Weakly informative sparse Dirichlet prior (0.35) so posterior adapts rapidly from experience."""
        alpha = {k: 0.35 for k in OUTCOME_CLASSES}
        screening = perception.get("screening", {})
        if screening.get("blocked"):
            alpha["blocked"] = 1.4
            return alpha, 1.5, 0.5
        if plan.get("requires_human_approval"):
            alpha["waiting"] = 1.4
            return alpha, 1.5, 0.5
        if int(plan.get("estimated_tokens", 0)) == 0:
            alpha["ok"] = 1.1
            return alpha, 1.5, 0.5
        alpha["ok"] = 0.85
        return alpha, 0.8, 1.2

    def execute(self, context: dict[str, Any]) -> OrganReport:
        t0 = time.perf_counter()
        phase = context.get("phase", "predict")

        if phase == "compare":
            return self._compare_and_update(context, t0)
        return self._predict(context, t0)

    def _predict(self, context: dict[str, Any], t0: float) -> OrganReport:
        plan = context.get("plan", {})
        perception = context.get("perception", {})
        memories_count = int(context.get("memories_count", len(context.get("retrieved_memories", []))))

        state_key = build_state_key(perception, plan, memories_count)
        action_key = infer_action_key(plan, perception)
        sa_key = f"{state_key}|{action_key}"

        learned = self._get_transition(sa_key)
        if learned is not None and int(learned["sample_count"]) > 0:
            alpha = dict(learned["alpha_counts"])
            det_alpha = float(learned["det_alpha"])
            det_beta = float(learned["det_beta"])
            sample_count = int(learned["sample_count"])
            avg_tokens = float(learned["avg_tokens_ema"])
            prior_td = float(learned["td_error_ema"])
            model_source = "learned_posterior"
        else:
            alpha, det_alpha, det_beta = self._prior_alpha(perception, plan)
            sample_count = 0
            avg_tokens = float(plan.get("estimated_tokens", 0))
            prior_td = 0.25
            model_source = "dirichlet_prior"

        total_alpha = sum(alpha.values())
        probs = {k: round(alpha.get(k, 1.0) / max(1e-6, total_alpha), 4) for k in OUTCOME_CLASSES}
        expected_status = max(probs.items(), key=lambda kv: kv[1])[0]
        predicted_prob = probs[expected_status]
        p_det = round(det_alpha / max(1e-6, det_alpha + det_beta), 4)
        expected_det = p_det >= 0.5

        # Entropy of predicted distribution quantifies epistemic transition uncertainty
        entropy = round(
            -sum(p * math.log2(max(1e-9, p)) for p in probs.values() if p > 0),
            4,
        )
        # Predictive confidence grows smoothly with sample count & posterior concentration
        sample_weight = sample_count / (sample_count + 3.0)
        confidence = round(max(0.25, min(0.99, predicted_prob * (0.55 + 0.45 * sample_weight))), 4)

        return OrganReport(
            organ_name=self.name,
            status=StepStatus.OK,
            payload={
                "state_key": state_key,
                "action_key": action_key,
                "state_action_key": sa_key,
                "model_source": model_source,
                "sample_count": sample_count,
                "expected_status": expected_status,
                "predicted_probability": predicted_prob,
                "expected_deterministic": expected_det,
                "deterministic_probability": p_det,
                "outcome_distribution": probs,
                "transition_entropy": entropy,
                "expected_td_error": round(prior_td, 4),
                "predicted_token_cost": round(avg_tokens, 1),
                "expected_effect": (
                    f"Posterior({sample_count} obs): P({expected_status})={predicted_prob:.2f}, "
                    f"P(det)={p_det:.2f}, H={entropy:.2f}"
                ),
            },
            confidence=confidence,
            deterministic=True,
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
        )

    def _compare_and_update(self, context: dict[str, Any], t0: float) -> OrganReport:
        prediction = context.get("prediction", {})
        observed = context.get("observed", {})
        cycle_id = str(context.get("cycle_id", "unknown"))
        regime_tag = str(context.get("regime_tag", "default"))

        expected_status = str(prediction.get("expected_status", "ok"))
        actual_status = str(observed.get("status", "ok"))
        expected_det = bool(prediction.get("expected_deterministic", True))
        actual_det = bool(observed.get("deterministic", True))
        actual_tokens = int(observed.get("tokens_used", 0))

        probs = dict(prediction.get("outcome_distribution", {}))
        p_actual = float(probs.get(actual_status, 0.2))
        predicted_prob = float(prediction.get("predicted_probability", 0.5))

        matched = (expected_status == actual_status) and (expected_det == actual_det)
        # Brier-style probabilistic error on actual outcome + TD value residual
        brier_term = round((1.0 - p_actual) ** 2, 4)
        reward = 1.0 if actual_status == "ok" else (0.4 if actual_status == "degraded" else 0.0)
        expected_value = float(probs.get("ok", 0.5)) + 0.4 * float(probs.get("degraded", 0.1))
        td_error = round(reward - expected_value, 4)
        prediction_error = round(0.5 * abs(td_error) + 0.5 * brier_term, 4)

        state_key = str(prediction.get("state_key", "unknown"))
        action_key = str(prediction.get("action_key", "ACT_DETERMINISTIC"))
        sa_key = str(prediction.get("state_action_key", f"{state_key}|{action_key}"))

        existing = self._get_transition(sa_key)
        if existing is not None:
            alpha = dict(existing["alpha_counts"])
            det_alpha = float(existing["det_alpha"])
            det_beta = float(existing["det_beta"])
            prev_td = float(existing["td_error_ema"])
            prev_tok = float(existing["avg_tokens_ema"])
            fisher = float(existing.get("fisher_precision", 0.0))
            anchor = dict(existing.get("anchor_alpha", {}))
            sample_count = int(existing["sample_count"])
        else:
            alpha = {k: 0.35 for k in OUTCOME_CLASSES}
            det_alpha, det_beta = 0.8, 0.8
            prev_td, prev_tok = 0.25, float(actual_tokens)
            fisher, anchor = 0.0, {}
            sample_count = 0

        # Bayesian Dirichlet-Beta online update with mild recency decay so adaptation stays responsive
        decay = 0.96
        for k in OUTCOME_CLASSES:
            alpha[k] = round(0.35 + decay * max(0.0, alpha.get(k, 0.35) - 0.35), 4)
        if actual_status in alpha:
            alpha[actual_status] = round(alpha[actual_status] + 1.0, 4)

        # EWC anchor pull prevents catastrophic drift when anchored
        if anchor and fisher > 0.0:
            ewc_pull = min(0.25, 0.05 * fisher)
            for k in OUTCOME_CLASSES:
                alpha[k] = round((1.0 - ewc_pull) * alpha[k] + ewc_pull * anchor.get(k, alpha[k]), 4)

        det_alpha = round(0.8 + decay * max(0.0, det_alpha - 0.8) + (1.0 if actual_det else 0.0), 4)
        det_beta = round(0.8 + decay * max(0.0, det_beta - 0.8) + (0.0 if actual_det else 1.0), 4)
        new_td_ema = round((1.0 - self.learning_rate) * prev_td + self.learning_rate * abs(td_error), 4)
        new_tok_ema = round((1.0 - self.learning_rate) * prev_tok + self.learning_rate * actual_tokens, 2)
        new_samples = sample_count + 1

        self._save_transition(
            sa_key=sa_key,
            state_key=state_key,
            action_key=action_key,
            alpha_counts=alpha,
            det_alpha=det_alpha,
            det_beta=det_beta,
            td_error_ema=new_td_ema,
            avg_tokens_ema=new_tok_ema,
            fisher_precision=fisher,
            anchor_alpha=anchor,
            sample_count=new_samples,
        )

        if self._store is not None:
            self._store.insert_prediction_history(
                cycle_id=cycle_id,
                state_action_key=sa_key,
                predicted_status=expected_status,
                predicted_prob=predicted_prob,
                actual_status=actual_status,
                matched=matched,
                brier_term=brier_term,
                td_error=td_error,
            )
            if self._continual is not None:
                self._continual.record_transition_experience(
                    state_key=state_key,
                    action_key=action_key,
                    observed_status=actual_status,
                    observed_det=actual_det,
                    observed_tokens=actual_tokens,
                    regime_tag=regime_tag,
                    td_error=td_error,
                )
                if new_samples % 5 == 0:
                    self._continual.consolidate_fisher_anchors()

        return OrganReport(
            organ_name=self.name,
            status=StepStatus.OK,
            payload={
                "state_action_key": sa_key,
                "matched_prediction": matched,
                "prediction_error": prediction_error,
                "brier_term": brier_term,
                "td_error": td_error,
                "td_error_ema": new_td_ema,
                "updated_sample_count": new_samples,
                "expected_status": expected_status,
                "actual_status": actual_status,
                "expected_deterministic": expected_det,
                "actual_deterministic": actual_det,
            },
            confidence=round(max(0.1, 1.0 - prediction_error), 4),
            deterministic=True,
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
        )
