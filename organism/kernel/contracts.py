"""Documented module contracts, enums, and state dataclasses for ORGANISM."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CycleStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    WAITING = "WAITING"
    DEFERRED = "DEFERRED"
    FAILED_SAFE = "FAILED_SAFE"

    @property
    def is_terminal(self) -> bool:
        return self in {
            CycleStatus.COMPLETED,
            CycleStatus.WAITING,
            CycleStatus.DEFERRED,
            CycleStatus.FAILED_SAFE,
        }


class TrustLevel(str, Enum):
    TRUSTED_OPERATOR = "trusted_operator"
    INTERNAL_SYSTEM = "internal_system"
    UNTRUSTED_EXTERNAL = "untrusted_external"


class EpistemicType(str, Enum):
    FACT = "fact"
    ASSUMPTION = "assumption"
    PREDICTION = "prediction"
    HYPOTHESIS = "hypothesis"
    UNKNOWN = "unknown"


class MemoryStatus(str, Enum):
    CANDIDATE = "candidate"
    TESTED = "tested"
    VERIFIED = "verified"
    APPROVED = "approved"
    ACTIVE = "active"
    INVALIDATED = "invalidated"
    DEPRECATED = "deprecated"


class StepStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class CognitiveEvent:
    event_id: str
    operation_id: str
    source: str
    trust_level: TrustLevel
    event_type: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    received_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["trust_level"] = self.trust_level.value
        return data

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CognitiveEvent":
        return cls(
            event_id=str(raw["event_id"]),
            operation_id=str(raw["operation_id"]),
            source=str(raw["source"]),
            trust_level=TrustLevel(raw["trust_level"]),
            event_type=str(raw.get("event_type", "observation")),
            content=str(raw["content"]),
            metadata=dict(raw.get("metadata", {})),
            received_at=str(raw.get("received_at", utc_now_iso())),
        )


@dataclass
class OrganReport:
    """Standardized return contract for every cognitive organ."""

    organ_name: str
    status: StepStatus
    payload: dict[str, Any]
    confidence: float = 1.0
    tokens_used: int = 0
    deterministic: bool = True
    error: str | None = None
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass
class StepTrace:
    step_number: int
    step_name: str
    organ: str
    status: StepStatus
    deterministic: bool
    tokens_used: int
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    timestamp: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StepTrace":
        return cls(
            step_number=int(raw["step_number"]),
            step_name=str(raw["step_name"]),
            organ=str(raw["organ"]),
            status=StepStatus(raw["status"]),
            deterministic=bool(raw["deterministic"]),
            tokens_used=int(raw.get("tokens_used", 0)),
            summary=str(raw.get("summary", "")),
            data=dict(raw.get("data", {})),
            duration_ms=float(raw.get("duration_ms", 0.0)),
            timestamp=str(raw.get("timestamp", utc_now_iso())),
        )


@dataclass
class CycleCheckpoint:
    cycle_id: str
    operation_id: str
    event_id: str
    current_step: int
    status: CycleStatus
    active_goal: str
    mode: str
    event_payload: dict[str, Any]
    workspace_snapshot: list[dict[str, Any]] = field(default_factory=list)
    perception_data: dict[str, Any] = field(default_factory=dict)
    retrieved_memories: list[dict[str, Any]] = field(default_factory=list)
    attention_scores: list[dict[str, Any]] = field(default_factory=list)
    plan: dict[str, Any] = field(default_factory=dict)
    prediction: dict[str, Any] = field(default_factory=dict)
    risk_assessment: dict[str, Any] = field(default_factory=dict)
    executive_decision: dict[str, Any] = field(default_factory=dict)
    action_result: dict[str, Any] = field(default_factory=dict)
    comparison: dict[str, Any] = field(default_factory=dict)
    metacognition: dict[str, Any] = field(default_factory=dict)
    homeostasis: dict[str, Any] = field(default_factory=dict)
    consolidation_candidates: list[dict[str, Any]] = field(default_factory=list)
    step_traces: list[StepTrace] = field(default_factory=list)
    tokens_used: int = 0
    outcome_summary: str = ""
    error_message: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["step_traces"] = [trace.to_dict() for trace in self.step_traces]
        return data

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CycleCheckpoint":
        return cls(
            cycle_id=str(raw["cycle_id"]),
            operation_id=str(raw["operation_id"]),
            event_id=str(raw["event_id"]),
            current_step=int(raw["current_step"]),
            status=CycleStatus(raw["status"]),
            active_goal=str(raw.get("active_goal", "")),
            mode=str(raw.get("mode", "auto")),
            event_payload=dict(raw.get("event_payload", {})),
            workspace_snapshot=list(raw.get("workspace_snapshot", [])),
            perception_data=dict(raw.get("perception_data", {})),
            retrieved_memories=list(raw.get("retrieved_memories", [])),
            attention_scores=list(raw.get("attention_scores", [])),
            plan=dict(raw.get("plan", {})),
            prediction=dict(raw.get("prediction", {})),
            risk_assessment=dict(raw.get("risk_assessment", {})),
            executive_decision=dict(raw.get("executive_decision", {})),
            action_result=dict(raw.get("action_result", {})),
            comparison=dict(raw.get("comparison", {})),
            metacognition=dict(raw.get("metacognition", {})),
            homeostasis=dict(raw.get("homeostasis", {})),
            consolidation_candidates=list(raw.get("consolidation_candidates", [])),
            step_traces=[StepTrace.from_dict(t) for t in raw.get("step_traces", [])],
            tokens_used=int(raw.get("tokens_used", 0)),
            outcome_summary=str(raw.get("outcome_summary", "")),
            error_message=raw.get("error_message"),
            created_at=str(raw.get("created_at", utc_now_iso())),
            updated_at=str(raw.get("updated_at", utc_now_iso())),
        )


class OrganContract(ABC):
    """Base contract for every modular cognitive organ."""

    name: str = "unnamed_organ"
    critical: bool = False

    @abstractmethod
    def execute(self, context: dict[str, Any]) -> OrganReport:
        """Process input context and return a structured OrganReport."""

    def health_check(self) -> dict[str, Any]:
        return {"organ": self.name, "critical": self.critical, "healthy": True}
