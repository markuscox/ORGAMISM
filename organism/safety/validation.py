"""State integrity verification and schema validation."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from organism.kernel.contracts import CycleCheckpoint, OrganReport


class IntegrityError(ValueError):
    """Raised when persisted state or an organ output fails validation."""


class IntegrityValidator:
    """Validates organ contracts and detects checkpoint/state tampering."""

    @staticmethod
    def compute_digest(payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def sign_snapshot(cls, snapshot: dict[str, Any]) -> dict[str, Any]:
        unsigned = {k: v for k, v in snapshot.items() if k != "integrity_sha256"}
        signed = dict(unsigned)
        signed["integrity_sha256"] = cls.compute_digest(unsigned)
        return signed

    @classmethod
    def verify_snapshot(cls, snapshot: dict[str, Any]) -> bool:
        expected = snapshot.get("integrity_sha256")
        if not expected:
            return False
        unsigned = {k: v for k, v in snapshot.items() if k != "integrity_sha256"}
        return cls.compute_digest(unsigned) == expected

    @staticmethod
    def validate_organ_report(report: OrganReport) -> None:
        if not isinstance(report, OrganReport):
            raise IntegrityError("Organ returned non-OrganReport object")
        if not report.organ_name:
            raise IntegrityError("OrganReport missing organ_name")
        if not (0.0 <= report.confidence <= 1.0):
            raise IntegrityError(f"Confidence {report.confidence} out of [0, 1] bounds")
        if report.tokens_used < 0:
            raise IntegrityError("tokens_used cannot be negative")

    @staticmethod
    def validate_checkpoint(checkpoint: CycleCheckpoint) -> None:
        if not checkpoint.cycle_id or not checkpoint.operation_id:
            raise IntegrityError("Checkpoint missing cycle_id or operation_id")
        if not (0 <= checkpoint.current_step <= 16):
            raise IntegrityError(f"Checkpoint step {checkpoint.current_step} out of range")
