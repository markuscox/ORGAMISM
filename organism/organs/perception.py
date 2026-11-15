"""Perception organ: multilingual (RU/EN) stimulus normalization, language & intent detection, and safety labeling."""

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


def detect_language(text: str) -> str:
    """Detect primary language script ('ru' vs 'en') deterministically from Unicode characters."""
    cyrillic = sum(1 for ch in text if "\u0400" <= ch <= "\u04ff")
    latin = sum(1 for ch in text if ("a" <= ch.lower() <= "z"))
    if cyrillic > 0 and cyrillic >= latin:
        return "ru"
    if cyrillic > 0 and latin > cyrillic:
        # Mixed string (e.g., Russian prompt citing an English config key)
        return "ru"
    return "en"


class PerceptionOrgan(OrganContract):
    name = "perception"
    critical = True

    MATH_PATTERN = re.compile(r"^[0-9\s+\-*/().,%]+$")
    CALC_PREFIX = re.compile(
        r"^(?:calc|compute|evaluate|solve|посчитай|вычисли|реши|сколько\s+будет)\s*[:\-]?\s*(.+)$",
        re.I,
    )
    CONTROL_COMMAND = re.compile(r"^/(start|help|status|approve|reject|memory|wake)\b(.*)$", re.I)

    # Structured triple assertion in EN or RU (e.g., "fact: X is Y", "факт: X — Y", "запомни: X = Y")
    FACT_TRIPLE_PREFIX = re.compile(
        r"^(?:fact|verify|record|remember|save|note|факт|запомни|сохрани|запиши|учти)\s*[:\-]?\s*(.+)$",
        re.I,
    )
    TRIPLE_SPLIT = re.compile(
        r"^(.+?)\s+(?:is|equals|равн[аоы]?|есть|это|=|—|-|:)\s+(.+)$",
        re.I,
    )

    HYPOTHESIS_ASSERTION = re.compile(
        r"^(?:hypothesis|assume|suppose|maybe|predict|гипотеза|предположим|допустим|возможно|прогноз)\s*[:\-]?\s*(.+)$",
        re.I,
    )
    QUERY_PREFIX = re.compile(
        r"^(?:query|recall|lookup|память|вспомни|найди|напомни|запрос)\s*[:\-]\s*(.+)$",
        re.I,
    )

    RU_QUESTION_START = re.compile(
        r"^(?:кто|что|где|когда|почему|зачем|как|сколько|какой|какая|какие|каков|помнишь|знаешь)\b",
        re.I,
    )
    EN_QUESTION_START = re.compile(
        r"^(?:who|what|where|when|why|how|which|do\s+you|did\s+i|can\s+you)\b",
        re.I,
    )
    MEMORY_RECALL_CUES = (
        "status",
        "what do you know",
        "recall",
        "remember",
        "what did i",
        "что ты знаешь",
        "что ты помнишь",
        "что я говорил",
        "что я просил",
        "вспомни",
        "помнишь",
        "напомни",
        "найди в памяти",
        "в памяти",
    )

    @classmethod
    def _extract_triple(cls, body: str) -> dict[str, str]:
        cleaned = body.strip().rstrip(".!")
        m = cls.TRIPLE_SPLIT.match(cleaned)
        if m:
            subj = m.group(1).strip()
            obj = m.group(2).strip()
            if subj and obj:
                return {"subject": subj, "predicate": "is", "object_value": obj}
        words = cleaned.split()
        if len(words) >= 3:
            subject = " ".join(words[:2])
            obj = " ".join(words[2:])
            return {"subject": subject, "predicate": "states", "object_value": obj}
        return {"subject": "note", "predicate": "states", "object_value": cleaned}

    def execute(self, context: dict[str, Any]) -> OrganReport:
        t0 = time.perf_counter()
        event: CognitiveEvent = context["event"]
        screening = SecurityPolicy.screen_input(event.content, event.trust_level)

        text = screening.sanitized_text.strip()
        language = detect_language(text)
        lowered = text.lower()
        is_question = (
            "?" in text
            or bool(self.RU_QUESTION_START.match(text))
            or bool(self.EN_QUESTION_START.match(text))
        )

        reliability = {
            TrustLevel.TRUSTED_OPERATOR: 0.95,
            TrustLevel.INTERNAL_SYSTEM: 0.9,
            TrustLevel.UNTRUSTED_EXTERNAL: 0.35,
        }[event.trust_level]

        detected_intent = "analysis"
        math_expr: str | None = None
        extracted_triple: dict[str, str] | None = None
        epistemic_hint = EpistemicType.UNKNOWN.value

        calc_match = self.CALC_PREFIX.match(text)
        if calc_match:
            candidate_expr = calc_match.group(1).strip().rstrip("?!.")
            if self.MATH_PATTERN.match(candidate_expr) or any(fn in candidate_expr for fn in ("sqrt", "sin", "cos", "log", "abs")):
                detected_intent = "math_computation"
                math_expr = candidate_expr
                epistemic_hint = EpistemicType.FACT.value
        elif self.MATH_PATTERN.match(text) and any(op in text for op in "+-*/%"):
            detected_intent = "math_computation"
            math_expr = text
            epistemic_hint = EpistemicType.FACT.value

        if detected_intent == "analysis":
            if self.CONTROL_COMMAND.match(text):
                detected_intent = "control_command"
                epistemic_hint = EpistemicType.FACT.value
            elif m := self.FACT_TRIPLE_PREFIX.match(text):
                body = m.group(1).strip()
                if body:
                    detected_intent = "knowledge_assertion"
                    extracted_triple = self._extract_triple(body)
                    epistemic_hint = (
                        EpistemicType.FACT.value
                        if event.trust_level != TrustLevel.UNTRUSTED_EXTERNAL
                        else EpistemicType.HYPOTHESIS.value
                    )
            elif self.HYPOTHESIS_ASSERTION.match(text):
                detected_intent = "hypothesis_evaluation"
                epistemic_hint = EpistemicType.HYPOTHESIS.value
            elif self.QUERY_PREFIX.match(text) or (
                is_question and any(cue in lowered for cue in self.MEMORY_RECALL_CUES)
            ) or any(cue in lowered for cue in ("что ты знаешь", "что ты помнишь", "найди в памяти", "what do you know", "what did i")):
                detected_intent = "memory_query"
                epistemic_hint = EpistemicType.FACT.value

        payload = {
            "normalized_text": text,
            "language": language,
            "is_question": is_question,
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
