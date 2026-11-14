"""Communication & action organ: unified bounded interface for internal actions and observations."""

from __future__ import annotations

import time
from typing import Any

from organism.kernel.contracts import OrganContract, OrganReport, StepStatus


class CommunicationOrgan(OrganContract):
    name = "communication"
    critical = False

    DECLARED_TOOLS: dict[str, dict[str, Any]] = {
        "internal_math": {
            "capability": "compute_math",
            "permission": "all",
            "cost_limit_tokens": 0,
            "timeout_ms": 500,
        },
        "internal_memory_rw": {
            "capability": "query_memory",
            "permission": "all",
            "cost_limit_tokens": 0,
            "timeout_ms": 500,
        },
        "gemini_synthesis": {
            "capability": "call_llm",
            "permission": "trusted_or_internal",
            "cost_limit_tokens": 25000,
            "timeout_ms": 20000,
        },
    }

    def execute(self, context: dict[str, Any]) -> OrganReport:
        t0 = time.perf_counter()
        reasoning_report = context.get("reasoning_report", {})
        decision = context.get("executive_decision", {})

        observation = {
            "decision_executed": decision.get("decision"),
            "status": reasoning_report.get("status", "ok"),
            "deterministic": reasoning_report.get("deterministic", True),
            "answer": reasoning_report.get("payload", {}).get("answer", ""),
            "epistemic_type": reasoning_report.get("payload", {}).get("epistemic_type", "unknown"),
            "declared_tools": list(self.DECLARED_TOOLS.keys()),
        }

        return OrganReport(
            organ_name=self.name,
            status=StepStatus.OK,
            payload=observation,
            confidence=1.0,
            deterministic=True,
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
        )
