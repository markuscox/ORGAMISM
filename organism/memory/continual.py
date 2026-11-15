"""Controlled continual-learning foundation: experience replay & EWC-inspired Fisher precision anchoring."""

from __future__ import annotations

from typing import Any

from organism.kernel.contracts import utc_now_iso
from .storage import SQLiteMemoryStore


OUTCOME_CLASSES = ("ok", "degraded", "blocked", "deferred", "waiting")


class ContinualLearningManager:
    """Prevents catastrophic forgetting across regime shifts via replay rehearsal & Fisher precision anchoring."""

    def __init__(self, store: SQLiteMemoryStore, ewc_lambda: float = 0.35) -> None:
        self._store = store
        self.ewc_lambda = ewc_lambda

    def record_transition_experience(
        self,
        state_key: str,
        action_key: str,
        observed_status: str,
        observed_det: bool,
        observed_tokens: int,
        regime_tag: str = "default",
        td_error: float = 0.0,
    ) -> str:
        priority = round(min(1.0, 0.25 + abs(td_error)), 4)
        return self._store.insert_replay_experience(
            state_key=state_key,
            action_key=action_key,
            observed_status=observed_status,
            observed_det=observed_det,
            observed_tokens=observed_tokens,
            regime_tag=regime_tag,
            priority=priority,
        )

    def consolidate_fisher_anchors(self) -> int:
        """Snapshot high-sample transition beliefs as Fisher-weighted anchors to resist forgetting."""
        transitions = self._store.list_world_transitions(limit=100)
        anchored = 0
        for tr in transitions:
            n = int(tr["sample_count"])
            if n < 3:
                continue
            alpha = dict(tr["alpha_counts"])
            total = sum(alpha.values())
            if total <= 0:
                continue
            probs = {k: alpha.get(k, 0.35) / total for k in OUTCOME_CLASSES}
            # Fisher information approximation for categorical Dirichlet posterior: ~ N / (p*(1-p)) bounded
            mean_fisher = round(min(10.0, n / max(0.1, sum(p * (1.0 - p) for p in probs.values()))), 4)
            self._store.upsert_world_transition(
                state_action_key=tr["state_action_key"],
                state_key=tr["state_key"],
                action_key=tr["action_key"],
                alpha_counts=alpha,
                det_alpha=tr["det_alpha"],
                det_beta=tr["det_beta"],
                td_error_ema=tr["td_error_ema"],
                avg_tokens_ema=tr["avg_tokens_ema"],
                fisher_precision=mean_fisher,
                anchor_alpha=alpha,
                sample_count=n,
            )
            anchored += 1
        return anchored

    def replay_rehearsal(self, batch_size: int = 12) -> dict[str, Any]:
        """Rehearse buffered past transitions using EWC anchor pull so prior regimes are retained."""
        experiences = self._store.list_replay_buffer(limit=batch_size)
        rehearsed = 0
        regimes_seen: set[str] = set()

        for exp in experiences:
            regimes_seen.add(exp["regime_tag"])
            sa_key = f"{exp['state_key']}|{exp['action_key']}"
            tr = self._store.get_world_transition(sa_key)
            if tr is None:
                continue

            alpha = dict(tr["alpha_counts"])
            anchor = dict(tr["anchor_alpha"]) if tr["anchor_alpha"] else {}
            fisher = float(tr.get("fisher_precision", 0.0))

            # Mild rehearsal reinforcement + EWC elastic pull toward anchored beliefs
            obs_status = exp["observed_status"]
            if obs_status in alpha:
                alpha[obs_status] = round(alpha[obs_status] + 0.25, 4)

            if anchor and fisher > 0.0:
                pull = min(0.5, self.ewc_lambda * (fisher / 10.0))
                for k in OUTCOME_CLASSES:
                    cur_v = alpha.get(k, 0.35)
                    anc_v = anchor.get(k, cur_v)
                    alpha[k] = round((1.0 - pull) * cur_v + pull * anc_v, 4)

            self._store.upsert_world_transition(
                state_action_key=sa_key,
                state_key=tr["state_key"],
                action_key=tr["action_key"],
                alpha_counts=alpha,
                det_alpha=tr["det_alpha"],
                det_beta=tr["det_beta"],
                td_error_ema=tr["td_error_ema"],
                avg_tokens_ema=tr["avg_tokens_ema"],
                fisher_precision=fisher,
                anchor_alpha=anchor,
                sample_count=tr["sample_count"],
            )
            rehearsed += 1

        return {
            "rehearsed_count": rehearsed,
            "regimes_covered": sorted(regimes_seen),
            "timestamp": utc_now_iso(),
        }
