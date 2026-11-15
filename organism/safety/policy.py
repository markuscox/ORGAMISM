"""Prompt-injection screening, secret redaction, and untrusted input isolation."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from organism.kernel.contracts import TrustLevel


@dataclass(frozen=True)
class ScreeningResult:
    sanitized_text: str
    injection_detected: bool
    injection_matches: list[str]
    secrets_redacted: int
    high_impact_requested: bool
    high_impact_reason: str | None
    blocked: bool
    block_reason: str | None


class SecurityPolicy:
    """Screens incoming content and outgoing prompts for injection and secret leakage."""

    INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("ignore_instructions", re.compile(r"ignore\s+(all\s+)?(previous|prior|system)\s+instructions?", re.I)),
        ("ignore_instructions_ru", re.compile(r"игнорируй\s+(все\s+)?(предыдущие|системные|прошлые)\s+инструкц", re.I)),
        ("override_policy", re.compile(r"(override|bypass|disable)\s+(safety|security|policy|rules|permissions)", re.I)),
        ("override_policy_ru", re.compile(r"(обойди|отключи|сбрось)\s+(защит|безопасност|правил|ограничен)", re.I)),
        ("grant_privilege", re.compile(r"(grant|elevate|give)\s+(yourself|me|root|admin)\s+(permission|access|privilege)", re.I)),
        ("reveal_secret", re.compile(r"(reveal|print|dump|exfiltrate|send)\s+(the\s+)?(api[_\s]?key|secret|token|credentials|env)", re.I)),
        ("reveal_secret_ru", re.compile(r"(покажи|выведи|раскрой|отправь|слей)\s+(все\s+)?(секрет|ключ|токен|парол)", re.I)),
        ("shell_execution", re.compile(r"(run|execute|eval|exec)\s+(shell|bash|python|arbitrary\s+code|rm\s+-rf|subprocess)", re.I)),
        ("shell_execution_ru", re.compile(r"(выполни|запусти)\s+(shell|bash|python|произвольн\w+\s+код|команд\w+\s+в\s+терминал)", re.I)),
        ("role_hijack", re.compile(r"^\s*(system|developer)\s*:\s*", re.I | re.M)),
    )

    HIGH_IMPACT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("external_publish", re.compile(r"\b(publish|deploy|push\s+to\s+main|send\s+email|post\s+tweet|external\s+api\s+write)\b", re.I)),
        ("destructive_mutation", re.compile(r"\b(delete\s+database|drop\s+table|erase\s+memory|reset\s+production)\b", re.I)),
        ("external_action", re.compile(r"\b(execute\s+external\s+action|transfer\s+funds|modify\s+repo)\b", re.I)),
    )

    SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"AIza[0-9A-Za-z\-_]{20,}"),
        re.compile(r"sk-[0-9A-Za-z\-_]{16,}"),
        re.compile(r"ghp_[0-9A-Za-z]{20,}"),
        re.compile(r"github_pat_[0-9A-Za-z_]{20,}"),
        re.compile(r"(?i)(GEMINI_API_KEY|TELEGRAM_BOT_TOKEN|ORGANISM_STATE_ENCRYPTION_KEY|ORGANISM_ADMIN_TOKEN|API_KEY|SECRET_KEY|ACCESS_TOKEN|PASSWORD)\s*[:=]\s*['\"]?([^\s'\"]{6,})['\"]?"),
        re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*"),
        re.compile(r"\b\d{7,12}:[A-Za-z0-9_-]{30,}\b"),
    )

    @classmethod
    def redact_secrets(cls, text: str) -> tuple[str, int]:
        if not text:
            return "", 0
        redacted = text
        count = 0

        # Redact live secret values if set in environment
        for env_name in (
            "GEMINI_API_KEY",
            "TELEGRAM_BOT_TOKEN",
            "ORGANISM_STATE_ENCRYPTION_KEY",
            "ORGANISM_ADMIN_TOKEN",
        ):
            live_val = os.environ.get(env_name, "").strip()
            if live_val and len(live_val) >= 8 and live_val in redacted:
                occurrences = redacted.count(live_val)
                redacted = redacted.replace(live_val, f"[REDACTED_{env_name}]")
                count += occurrences

        for idx, pattern in enumerate(cls.SECRET_PATTERNS):
            def _repl(match: re.Match[str], p_idx: int = idx) -> str:
                nonlocal count
                count += 1
                if p_idx == 4:
                    return f"{match.group(1)}=[REDACTED_SECRET]"
                return "[REDACTED_SECRET]"

            redacted = pattern.sub(_repl, redacted)

        return redacted, count

    @classmethod
    def screen_input(cls, raw_text: str, trust_level: TrustLevel) -> ScreeningResult:
        sanitized, secrets_count = cls.redact_secrets(raw_text)

        injection_matches: list[str] = []
        for label, pattern in cls.INJECTION_PATTERNS:
            if pattern.search(sanitized):
                injection_matches.append(label)

        high_impact_reason: str | None = None
        for label, pattern in cls.HIGH_IMPACT_PATTERNS:
            if pattern.search(sanitized):
                high_impact_reason = label
                break

        injection_detected = len(injection_matches) > 0
        blocked = False
        block_reason: str | None = None

        if injection_detected and trust_level == TrustLevel.UNTRUSTED_EXTERNAL:
            blocked = True
            block_reason = (
                "Prompt-injection or privilege-escalation pattern detected in untrusted external input: "
                + ", ".join(injection_matches)
            )
        elif any(m in {"shell_execution", "grant_privilege", "override_policy", "reveal_secret"} for m in injection_matches):
            blocked = True
            block_reason = (
                "Prohibited system-override or secret-exfiltration request blocked by policy: "
                + ", ".join(injection_matches)
            )

        return ScreeningResult(
            sanitized_text=sanitized,
            injection_detected=injection_detected,
            injection_matches=injection_matches,
            secrets_redacted=secrets_count,
            high_impact_requested=high_impact_reason is not None,
            high_impact_reason=high_impact_reason,
            blocked=blocked,
            block_reason=block_reason,
        )
