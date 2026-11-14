"""Append-only safety audit logger."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from organism.kernel.contracts import utc_now_iso
from .policy import SecurityPolicy

if TYPE_CHECKING:
    from organism.memory.storage import SQLiteMemoryStore


class SafetyAuditLogger:
    def __init__(self, store: "SQLiteMemoryStore") -> None:
        self._store = store

    def log(
        self,
        cycle_id: str,
        severity: str,
        rule_triggered: str,
        action_decision: str,
        excerpt: str,
    ) -> str:
        redacted_excerpt, _ = SecurityPolicy.redact_secrets(excerpt)
        audit_id = f"aud_{uuid.uuid4().hex[:12]}"
        self._store.insert_safety_audit(
            audit_id=audit_id,
            cycle_id=cycle_id,
            severity=severity,
            rule_triggered=rule_triggered,
            action_decision=action_decision,
            excerpt=redacted_excerpt[:400],
            created_at=utc_now_iso(),
        )
        return audit_id
