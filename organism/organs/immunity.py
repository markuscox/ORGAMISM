"""Immunity & safety organ: evaluates capabilities, budgets, injection risks, and audit logs."""

from __future__ import annotations

import time
from typing import Any

from organism.kernel.contracts import OrganContract, OrganReport, StepStatus, TrustLevel
from organism.models.usage_budget import UsageBudgetManager
from organism.safety.audit import SafetyAuditLogger
from organism.safety.permissions import Capability, PermissionPolicy


class ImmunityOrgan(OrganContract):
    name = "immunity"
    critical = True

    def __init__(self, audit: SafetyAuditLogger, budget: UsageBudgetManager) -> None:
        self._audit = audit
        self._budget = budget

    def execute(self, context: dict[str, Any]) -> OrganReport:
        t0 = time.perf_counter()
        cycle_id = str(context["cycle_id"])
        perception = context.get("perception", {})
        plan = context.get("plan", {})
        trust_level = TrustLevel(perception.get("trust_level", TrustLevel.UNTRUSTED_EXTERNAL.value))
        screening = perception.get("screening", {})
        approved_by_human = bool(context.get("approved_by_human", False))
        mode = str(context.get("mode", "auto"))

        if screening.get("secrets_redacted", 0) > 0:
            self._audit.log(
                cycle_id=cycle_id,
                severity="MEDIUM",
                rule_triggered="secret_redaction",
                action_decision="sanitized",
                excerpt=f"Redacted {screening['secrets_redacted']} secret pattern(s) from input.",
            )

        if screening.get("blocked"):
            reason = str(screening.get("block_reason", "Blocked by security policy"))
            self._audit.log(
                cycle_id=cycle_id,
                severity="HIGH",
                rule_triggered=",".join(screening.get("injection_matches", ["policy_block"])),
                action_decision="blocked",
                excerpt=reason,
            )
            return OrganReport(
                organ_name=self.name,
                status=StepStatus.BLOCKED,
                payload={"blocked": True, "reason": reason, "budget_ok": True},
                confidence=1.0,
                deterministic=True,
                error=reason,
                duration_ms=round((time.perf_counter() - t0) * 1000, 3),
            )

        if plan.get("requires_human_approval"):
            permitted, perm_reason = PermissionPolicy.evaluate(
                trust_level=trust_level,
                capability=Capability.EXTERNAL_ACTION_REQUEST,
                approved_by_human=approved_by_human,
            )
            if not permitted:
                self._audit.log(
                    cycle_id=cycle_id,
                    severity="MEDIUM",
                    rule_triggered=str(screening.get("high_impact_reason", "human_approval_gate")),
                    action_decision="requires_approval",
                    excerpt=perm_reason,
                )
                return OrganReport(
                    organ_name=self.name,
                    status=StepStatus.OK,
                    payload={
                        "blocked": False,
                        "requires_approval": True,
                        "reason": perm_reason,
                        "budget_ok": True,
                    },
                    confidence=1.0,
                    deterministic=True,
                    duration_ms=round((time.perf_counter() - t0) * 1000, 3),
                )

        est_tokens = int(plan.get("estimated_tokens", 0))
        budget_ok = True
        budget_reason = "Deterministic zero-token execution"
        if est_tokens > 0 and mode != "deterministic_only":
            cap_ok, cap_reason = PermissionPolicy.evaluate(trust_level, Capability.CALL_LLM)
            if not cap_ok:
                # Untrusted external inputs cannot force paid/free LLM token spend on arbitrary prompts
                self._audit.log(
                    cycle_id=cycle_id,
                    severity="LOW",
                    rule_triggered="untrusted_llm_restriction",
                    action_decision="sanitized",
                    excerpt=cap_reason,
                )
            budget_ok, budget_reason = self._budget.can_spend(est_tokens)
            if not budget_ok:
                self._audit.log(
                    cycle_id=cycle_id,
                    severity="MEDIUM",
                    rule_triggered="token_budget_exhausted",
                    action_decision="deferred",
                    excerpt=budget_reason,
                )

        return OrganReport(
            organ_name=self.name,
            status=StepStatus.OK,
            payload={
                "blocked": False,
                "budget_ok": budget_ok,
                "budget_reason": budget_reason,
                "trust_level": trust_level.value,
            },
            confidence=1.0,
            deterministic=True,
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
        )
