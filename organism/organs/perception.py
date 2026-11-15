"""Perception organ: normalizes stimuli, detects intent/epistemic cues, and labels untrusted data."""

from __future__ import annotations

import re
import time
from typing import Any

from organism.kernel.contracts import (
    CognitiveEvent,
    EpistemicType,
    OrganContract,
    OrganReport,
    StepStatus,
    TrustLevel,
)
from organism.safety.policy import SecurityPolicy


class PerceptionOrgan(OrganContract):
    name = "perception"
    critical = True

    MATH_PATTERN = re.compile(r"^[0-9\s+\-*/().,%]+$")
    CALC_PREFIX = re.compile(r"^(?:calc|compute|evaluate|solve)\s*[:\-]?\s*(.+)$", re.I)
    FACT_ASSERTION = re.compile(
        r"^(?:fact|verify|record)\s*[:\-]?\s*([a-zA-Z0-9_.\- ]+?)\s+(?:is|equals|=|:)\s+(.+)$",
        re.I,
    )
    HYPOTHESIS_ASSERTION = re.compile(
        r"^(?:hypothesis|assume|suppose|maybe|predict)\s*[:\-]?\s*(.+)$",
        re.I,
    )
    QUERY_PREFIX = re.compile(r"^(?:query|recall|lookup)\s*[:\-]\s*(.+)$", re.I)

    def execute(self, context: dict[str, Any]) -> OrganReport:
        t0 = time.perf_counter()
        event: CognitiveEvent = context["event"]
        screening = SecurityPolicy.screen_input(event.content, event.trust_level)

        text = screening.sanitized_text.strip()
        reliability = {
            TrustLevel.TRUSTED_OPERATOR: 0.95,
            TrustLevel.INTERNAL_SYSTEM: 0.9,
            TrustLevel.UNTRUSTED_EXTERNAL: 0.35,
        }[event.trust_level]

        # Classify intent & epistemic framing deterministically
        detected_intent = "analysis"
        math_expr: str | None = None
        extracted_triple: dict[str, str] | None = None
        epistemic_hint = EpistemicType.UNKNOWN.value

        calc_match = self.CALC_PREFIX.match(text)
        if calc_match:
            detected_intent = "math_computation"
            math_expr = calc_match.group(1).strip()
            epistemic_hint = EpistemicType.FACT.value
        elif self.MATH_PATTERN.match(text) and any(op in text for op in "+-*/%"):
            detected_intent = "math_computation"
            math_expr = text
            epistemic_hint = EpistemicType.FACT.value
        elif m := self.FACT_ASSERTION.match(text):
            detected_intent = "knowledge_assertion"
            extracted_triple = {
                "subject": m.group(1).strip(),
                "predicate": "is",
                "object_value": m.group(2).strip().rstrip("."),
            }
            epistemic_hint = (
                EpistemicType.FACT.value
                if event.trust_level != TrustLevel.UNTRUSTED_EXTERNAL
                else EpistemicType.HYPOTHESIS.value
            )
        elif m := self.HYPOTHESIS_ASSERTION.match(text):
            detected_intent = "hypothesis_evaluation"
            epistemic_hint = EpistemicType.HYPOTHESIS.value
        elif self.QUERY_PREFIX.match(text) or (
            "?" in text and any(k in text.lower() for k in ("status", "what do you know", "recall", "remember"))
        ):
            detected_intent = "memory_query"
            epistemic_hint = EpistemicType.FACT.value

        payload = {
            "normalized_text": text,
            "source": event.source,
            "trust_level": event.trust_level.value,
            "reliability": reliability,
            "detected_intent": detected_intent,
            "math_expression": math_expr,
            "extracted_triple": extracted_triple,
            "epistemic_hint": epistemic_hint,
            "is_untrusted_data": event.trust_level == TrustLevel.UNTRUSTED_EXTERNAL,
            "screening": {
                "injection_detected": screening.injection_detected,
                "injection_matches": screening.injection_matches,
                "secrets_redacted": screening.secrets_redacted,
                "high_impact_requested": screening.high_impact_requested,
                "high_impact_reason": screening.high_impact_reason,
                "blocked": screening.blocked,
                "block_reason": screening.block_reason,
            },
        }

        status = StepStatus.BLOCKED if screening.blocked else StepStatus.OK
        return OrganReport(
            organ_name=self.name,
            status=status,
            payload=payload,
            confidence=reliability,
            tokens_used=0,
            deterministic=True,
            error=screening.block_reason,
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
        )
