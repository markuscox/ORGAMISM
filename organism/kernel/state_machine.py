"""Deterministic 16-step state machine for the ORGANISM cognitive cycle."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import CycleStatus


@dataclass(frozen=True)
class CycleStepSpec:
    number: int
    name: str
    organ: str
    description: str


CYCLE_STEPS: tuple[CycleStepSpec, ...] = (
    CycleStepSpec(1, "Receive Event", "scheduler", "Receive event or identify pending work"),
    CycleStepSpec(2, "Perceive & Classify", "perception", "Normalize input, source, trust level, and safety screen"),
    CycleStepSpec(3, "Retrieve Memories", "memory_retrieval", "Retrieve relevant episodic, semantic, and working memories"),
    CycleStepSpec(4, "Evaluate Attention", "attention", "Score relevance, novelty, urgency, and uncertainty"),
    CycleStepSpec(5, "Update Workspace", "workspace", "Load capacity-bounded Global Cognitive Workspace"),
    CycleStepSpec(6, "Identify Goals & Constraints", "motivation", "Resolve active goals and homeostatic constraints"),
    CycleStepSpec(7, "Construct Plan", "planner", "Decompose goal into steps, assumptions, and failure points"),
    CycleStepSpec(8, "Predict Outcomes", "world_model", "Predict consequences and expected state transitions"),
    CycleStepSpec(9, "Evaluate Uncertainty & Risk", "immunity", "Assess epistemic uncertainty, token budget, and safety policy"),
    CycleStepSpec(10, "Executive Decision", "executive", "Decide deterministically to act, investigate, wait, or defer"),
    CycleStepSpec(11, "Execute Permitted Operation", "reasoning_and_action", "Run deterministic logic or budgeted model operation"),
    CycleStepSpec(12, "Observe Result", "communication", "Capture execution observation and side-effect status"),
    CycleStepSpec(13, "Compare Prediction vs Result", "world_model", "Compute prediction error and verify invariants"),
    CycleStepSpec(14, "Update World & Metacognition", "metacognition", "Update calibration, confidence, and failure counters"),
    CycleStepSpec(15, "Record Event & Checkpoint", "episodic_memory", "Persist provenance-preserving episode and checkpoint"),
    CycleStepSpec(16, "Consolidate Memory", "learning", "Stage candidate durable facts and check contradictions"),
)


class InvalidStateTransitionError(RuntimeError):
    """Raised when an illegal cognitive cycle transition is attempted."""


class CycleStateMachine:
    """Enforces deterministic step progression and legal terminal states."""

    LEGAL_TRANSITIONS: dict[CycleStatus, set[CycleStatus]] = {
        CycleStatus.RUNNING: {
            CycleStatus.RUNNING,
            CycleStatus.COMPLETED,
            CycleStatus.WAITING,
            CycleStatus.DEFERRED,
            CycleStatus.FAILED_SAFE,
        },
        CycleStatus.WAITING: {
            CycleStatus.RUNNING,
            CycleStatus.COMPLETED,
            CycleStatus.FAILED_SAFE,
        },
        CycleStatus.DEFERRED: {
            CycleStatus.RUNNING,
            CycleStatus.FAILED_SAFE,
        },
        CycleStatus.COMPLETED: set(),
        CycleStatus.FAILED_SAFE: set(),
    }

    @classmethod
    def validate_step(cls, current_step: int, next_step: int) -> None:
        if next_step < 1 or next_step > 16:
            raise InvalidStateTransitionError(f"Step {next_step} outside valid range 1..16")
        if next_step != current_step + 1 and not (current_step == 0 and next_step == 1):
            raise InvalidStateTransitionError(
                f"Illegal step jump from {current_step} to {next_step}"
            )

    @classmethod
    def validate_status_transition(cls, current: CycleStatus, target: CycleStatus) -> None:
        if target not in cls.LEGAL_TRANSITIONS[current]:
            raise InvalidStateTransitionError(
                f"Illegal cycle status transition: {current.value} -> {target.value}"
            )
