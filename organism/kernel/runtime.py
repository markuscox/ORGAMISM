"""Central Cognitive Kernel orchestrating the 16-step recoverable wake cycle."""

from __future__ import annotations

import uuid
from typing import Any, Callable

from organism.config.settings import OrganismConfig, load_config
from organism.kernel.contracts import (
    CognitiveEvent,
    CycleCheckpoint,
    CycleStatus,
    EpistemicType,
    OrganContract,
    OrganReport,
    StepStatus,
    StepTrace,
    TrustLevel,
    utc_now_iso,
)
from organism.kernel.event_bus import EventBus
from organism.kernel.scheduler import WakeScheduler
from organism.kernel.state_machine import CYCLE_STEPS, CycleStateMachine
from organism.memory.consolidation import MemoryConsolidator
from organism.memory.knowledge_graph import TemporalKnowledgeGraph
from organism.memory.retrieval import MemoryRetriever
from organism.memory.storage import SQLiteMemoryStore
from organism.models.context_compiler import ContextCompiler
from organism.models.gemini import GeminiProvider
from organism.models.provider import ModelProvider
from organism.models.usage_budget import UsageBudgetManager
from organism.organs.attention import AttentionOrgan
from organism.organs.communication import CommunicationOrgan
from organism.organs.episodic_memory import EpisodicMemoryOrgan
from organism.organs.executive import ExecutiveOrgan
from organism.organs.immunity import ImmunityOrgan
from organism.organs.learning import LearningOrgan
from organism.organs.metacognition import MetacognitionOrgan
from organism.organs.motivation import MotivationOrgan
from organism.organs.perception import PerceptionOrgan
from organism.organs.planner import PlannerOrgan
from organism.organs.procedural_memory import ProceduralMemoryOrgan
from organism.organs.reasoning import ReasoningOrgan
from organism.organs.semantic_memory import SemanticMemoryOrgan
from organism.organs.working_memory import WorkingMemoryOrgan
from organism.organs.workspace import GlobalWorkspaceOrgan
from organism.organs.world_model import WorldModelOrgan
from organism.safety.audit import SafetyAuditLogger
from organism.safety.validation import IntegrityValidator


class SimulatedCrashInterrupt(RuntimeError):
    """Raised intentionally in tests/simulations to verify crash-restart checkpoint resumption."""


class CognitiveKernel:
    """Modular cognitive kernel connecting independent, fault-isolated organs."""

    def __init__(
        self,
        config: OrganismConfig | None = None,
        provider: ModelProvider | None = None,
    ) -> None:
        self.config = config or load_config()
        self.store = SQLiteMemoryStore(
            db_path=self.config.db_path,
            snapshot_path=self.config.snapshot_path,
            organism_id=self.config.organism_id,
            version=self.config.version,
        )
        self.kg = TemporalKnowledgeGraph(self.store)
        self.retriever = MemoryRetriever(self.store)
        self.consolidator = MemoryConsolidator(self.store, self.kg)
        self.budget = UsageBudgetManager(self.store, self.config)
        self.compiler = ContextCompiler(char_limit=self.config.context_char_limit)
        self.audit = SafetyAuditLogger(self.store)
        self.event_bus = EventBus(self.store)
        self.scheduler = WakeScheduler(self.store)

        self.provider: ModelProvider = provider or GeminiProvider(
            model_name=self.config.model_name,
            timeout_seconds=self.config.timeout_seconds,
            max_retries=self.config.max_retries,
            backoff_base_seconds=self.config.backoff_base_seconds,
        )

        # Initialize independent cognitive organs
        self.perception = PerceptionOrgan()
        self.attention = AttentionOrgan()
        self.workspace = GlobalWorkspaceOrgan(capacity=self.config.workspace_capacity)
        self.working_memory = WorkingMemoryOrgan(
            self.store,
            capacity=self.config.working_memory_capacity,
            ttl_cycles=self.config.working_memory_ttl_cycles,
        )
        self.episodic_memory = EpisodicMemoryOrgan(self.store)
        self.semantic_memory = SemanticMemoryOrgan(self.store, self.kg)
        self.procedural_memory = ProceduralMemoryOrgan(self.store)
        self.reasoning = ReasoningOrgan(self.provider, self.budget, self.compiler)
        self.planner = PlannerOrgan()
        self.world_model = WorldModelOrgan()
        self.executive = ExecutiveOrgan()
        self.metacognition = MetacognitionOrgan()
        self.motivation = MotivationOrgan()
        self.learning = LearningOrgan(self.consolidator)
        self.immunity = ImmunityOrgan(self.audit, self.budget)
        self.communication = CommunicationOrgan()

    def _run_organ_isolated(
        self,
        organ: OrganContract,
        context: dict[str, Any],
        fault_organ: str | None = None,
    ) -> OrganReport:
        """Executes an organ inside a fault-isolation boundary."""
        try:
            if fault_organ and organ.name == fault_organ:
                raise RuntimeError(f"Injected test fault in organ '{organ.name}'")
            report = organ.execute(context)
            IntegrityValidator.validate_organ_report(report)
            return report
        except Exception as exc:
            return OrganReport(
                organ_name=organ.name,
                status=StepStatus.ERROR,
                payload={"isolated_failure": True, "error": str(exc)},
                confidence=0.0,
                tokens_used=0,
                deterministic=True,
                error=f"Isolated organ failure ({organ.name}): {exc}",
            )

    def run_cycle(
        self,
        event: CognitiveEvent,
        mode: str = "auto",
        approved_by_human: bool = False,
        simulate_crash_at_step: int | None = None,
        simulate_fault_organ: str | None = None,
    ) -> CycleCheckpoint:
        """Execute a discrete 16-step cognitive wake cycle with idempotency and checkpoints."""
        # Idempotency check: never silently repeat an already completed operation
        existing_done = self.store.check_idempotency(event.operation_id)
        if existing_done is not None:
            prior_cp = self.store.get_checkpoint(existing_done["cycle_id"])
            if prior_cp is not None:
                return prior_cp

        cycle_id = f"cyc_{uuid.uuid4().hex[:12]}"
        identity = self.store.get_identity()
        goal = (identity.get("active_goals") or ["Maintain cognitive consistency"])[0]

        checkpoint = CycleCheckpoint(
            cycle_id=cycle_id,
            operation_id=event.operation_id,
            event_id=event.event_id,
            current_step=0,
            status=CycleStatus.RUNNING,
            active_goal=goal,
            mode=mode,
            event_payload=event.to_dict(),
        )
        self.store.save_checkpoint(checkpoint)
        return self._execute_from_step(
            checkpoint=checkpoint,
            event=event,
            approved_by_human=approved_by_human,
            simulate_crash_at_step=simulate_crash_at_step,
            simulate_fault_organ=simulate_fault_organ,
        )

    def resume_cycle(
        self,
        cycle_id: str | None = None,
        approved_by_human: bool = False,
        simulate_fault_organ: str | None = None,
    ) -> CycleCheckpoint | None:
        """Resume an interrupted RUNNING or WAITING cycle from its last saved step."""
        checkpoint = (
            self.store.get_checkpoint(cycle_id)
            if cycle_id
            else self.scheduler.find_resumable_checkpoint()
        )
        if checkpoint is None:
            return None
        if checkpoint.status not in {CycleStatus.RUNNING, CycleStatus.WAITING}:
            return checkpoint

        if checkpoint.status == CycleStatus.WAITING:
            CycleStateMachine.validate_status_transition(checkpoint.status, CycleStatus.RUNNING)
            checkpoint.status = CycleStatus.RUNNING
            # Re-evaluate from Step 9 when human approval is provided
            if approved_by_human and checkpoint.current_step >= 9:
                checkpoint.current_step = 8
                checkpoint.step_traces = [t for t in checkpoint.step_traces if t.step_number <= 8]
            self.store.save_checkpoint(checkpoint)

        event = CognitiveEvent.from_dict(checkpoint.event_payload)
        return self._execute_from_step(
            checkpoint=checkpoint,
            event=event,
            approved_by_human=approved_by_human,
            simulate_crash_at_step=None,
            simulate_fault_organ=simulate_fault_organ,
        )

    def approve_cycle(self, cycle_id: str, approve: bool) -> CycleCheckpoint | None:
        checkpoint = self.store.get_checkpoint(cycle_id)
        if checkpoint is None:
            return None
        if checkpoint.status != CycleStatus.WAITING:
            return checkpoint

        if not approve:
            CycleStateMachine.validate_status_transition(checkpoint.status, CycleStatus.FAILED_SAFE)
            checkpoint.status = CycleStatus.FAILED_SAFE
            checkpoint.outcome_summary = "Human operator rejected high-impact action; terminated safely."
            self.audit.log(
                cycle_id=cycle_id,
                severity="LOW",
                rule_triggered="human_approval_rejected",
                action_decision="blocked",
                excerpt=checkpoint.outcome_summary,
            )
            self.store.save_checkpoint(checkpoint)
            self.store.record_idempotency(
                checkpoint.operation_id, cycle_id, CycleStatus.FAILED_SAFE, checkpoint.outcome_summary
            )
            return checkpoint

        return self.resume_cycle(cycle_id=cycle_id, approved_by_human=True)

    def _execute_from_step(
        self,
        checkpoint: CycleCheckpoint,
        event: CognitiveEvent,
        approved_by_human: bool,
        simulate_crash_at_step: int | None,
        simulate_fault_organ: str | None,
    ) -> CycleCheckpoint:
        degraded_organs: list[str] = []
        identity = self.store.get_identity()
        cycle_number = int(identity.get("total_cycles", 0)) + 1

        def record_step(
            step_num: int,
            organ_name: str,
            status: StepStatus,
            deterministic: bool,
            tokens_used: int,
            summary: str,
            data: dict[str, Any],
            duration_ms: float = 0.0,
        ) -> None:
            CycleStateMachine.validate_step(checkpoint.current_step, step_num)
            checkpoint.current_step = step_num
            checkpoint.tokens_used += tokens_used
            step_spec = CYCLE_STEPS[step_num - 1]
            checkpoint.step_traces.append(
                StepTrace(
                    step_number=step_num,
                    step_name=step_spec.name,
                    organ=organ_name,
                    status=status,
                    deterministic=deterministic,
                    tokens_used=tokens_used,
                    summary=summary,
                    data=data,
                    duration_ms=duration_ms,
                )
            )
            self.store.save_checkpoint(checkpoint)

        def check_crash(step_num: int) -> None:
            if simulate_crash_at_step is not None and step_num == simulate_crash_at_step:
                raise SimulatedCrashInterrupt(
                    f"Simulated process crash after persisting step {step_num} checkpoint."
                )

        try:
            # Step 1: Receive Event
            if checkpoint.current_step < 1:
                record_step(
                    1,
                    "scheduler",
                    StepStatus.OK,
                    True,
                    0,
                    f"Received event '{event.event_id}' from {event.source} ({event.trust_level.value})",
                    {"event_id": event.event_id, "operation_id": event.operation_id},
                )
                check_crash(1)

            # Step 2: Perceive & Classify
            if checkpoint.current_step < 2:
                rep = self._run_organ_isolated(self.perception, {"event": event}, simulate_fault_organ)
                if rep.status == StepStatus.ERROR:
                    return self._fail_safe(checkpoint, event, rep.error or "Critical perception failure")
                checkpoint.perception_data = rep.payload
                record_step(
                    2,
                    self.perception.name,
                    rep.status,
                    rep.deterministic,
                    rep.tokens_used,
                    f"Intent={rep.payload.get('detected_intent')}, trust={rep.payload.get('trust_level')}, blocked={rep.payload.get('screening', {}).get('blocked')}",
                    rep.payload,
                    rep.duration_ms,
                )
                check_crash(2)

            # Step 3: Retrieve Memories
            if checkpoint.current_step < 3:
                query = str(checkpoint.perception_data.get("normalized_text", event.content))
                memories = self.retriever.retrieve(query, top_k=self.config.retrieval_top_k)
                checkpoint.retrieved_memories = memories
                record_step(
                    3,
                    "memory_retrieval",
                    StepStatus.OK,
                    True,
                    0,
                    f"Retrieved {len(memories)} relevant memory item(s)",
                    {"count": len(memories), "items": memories},
                )
                check_crash(3)

            # Step 4: Evaluate Attention
            if checkpoint.current_step < 4:
                rep = self._run_organ_isolated(
                    self.attention,
                    {
                        "perception": checkpoint.perception_data,
                        "retrieved_memories": checkpoint.retrieved_memories,
                        "active_goals": identity.get("active_goals", []),
                    },
                    simulate_fault_organ,
                )
                if rep.status == StepStatus.ERROR:
                    degraded_organs.append(self.attention.name)
                    ranked = [{"item_id": "current_stimulus", "layer": "perception", "summary": event.content[:180], "epistemic_type": "unknown", "salience": 0.8, "source": event.source}]
                else:
                    ranked = rep.payload.get("ranked_items", [])
                checkpoint.attention_scores = ranked
                record_step(
                    4,
                    self.attention.name,
                    rep.status if rep.status != StepStatus.ERROR else StepStatus.DEGRADED,
                    True,
                    0,
                    f"Ranked {len(ranked)} attention item(s) by salience",
                    {"ranked_items": ranked[:5]},
                    rep.duration_ms,
                )
                check_crash(4)

            # Step 5: Update Global Workspace & Working Memory
            if checkpoint.current_step < 5:
                ws_rep = self._run_organ_isolated(
                    self.workspace,
                    {"attention_ranked": checkpoint.attention_scores, "cycle_number": cycle_number},
                    simulate_fault_organ,
                )
                wm_rep = self._run_organ_isolated(
                    self.working_memory,
                    {
                        "cycle_number": cycle_number,
                        "slot_key": f"stimulus_{event.event_id}",
                        "slot_value": {
                            "intent": checkpoint.perception_data.get("detected_intent"),
                            "text": str(checkpoint.perception_data.get("normalized_text", ""))[:180],
                        },
                        "priority": 0.85,
                        "epistemic_type": checkpoint.perception_data.get("epistemic_hint", EpistemicType.UNKNOWN.value),
                        "source": event.source,
                    },
                    simulate_fault_organ,
                )
                if ws_rep.status == StepStatus.ERROR:
                    degraded_organs.append(self.workspace.name)
                if wm_rep.status == StepStatus.ERROR:
                    degraded_organs.append(self.working_memory.name)
                checkpoint.workspace_snapshot = ws_rep.payload.get("items", [])
                record_step(
                    5,
                    self.workspace.name,
                    StepStatus.OK if not (ws_rep.status == StepStatus.ERROR or wm_rep.status == StepStatus.ERROR) else StepStatus.DEGRADED,
                    True,
                    0,
                    f"Workspace holds {len(checkpoint.workspace_snapshot)}/{self.config.workspace_capacity} bounded item(s)",
                    {"workspace": checkpoint.workspace_snapshot, "working_memory_slots": wm_rep.payload.get("active_slots", 0)},
                    ws_rep.duration_ms + wm_rep.duration_ms,
                )
                check_crash(5)

            # Step 6: Identify Goals & Homeostatic Constraints
            if checkpoint.current_step < 6:
                rep = self._run_organ_isolated(
                    self.motivation,
                    {
                        "prior_homeostasis": identity.get("homeostasis", {}),
                        "budget_totals": self.budget.get_today_totals(),
                        "active_goals": identity.get("active_goals", []),
                    },
                    simulate_fault_organ,
                )
                if rep.status == StepStatus.ERROR:
                    degraded_organs.append(self.motivation.name)
                    checkpoint.homeostasis = identity.get("homeostasis", {})
                else:
                    checkpoint.homeostasis = rep.payload.get("homeostasis", {})
                record_step(
                    6,
                    self.motivation.name,
                    rep.status if rep.status != StepStatus.ERROR else StepStatus.DEGRADED,
                    True,
                    0,
                    f"Resolved {len(identity.get('active_goals', []))} goal(s) and homeostatic drives",
                    rep.payload,
                    rep.duration_ms,
                )
                check_crash(6)

            # Step 7: Construct Plan
            if checkpoint.current_step < 7:
                rep = self._run_organ_isolated(
                    self.planner,
                    {"perception": checkpoint.perception_data, "mode": checkpoint.mode},
                    simulate_fault_organ,
                )
                if rep.status == StepStatus.ERROR:
                    degraded_organs.append(self.planner.name)
                    checkpoint.plan = {"steps": ["Safe deterministic fallback"], "estimated_tokens": 0, "requires_human_approval": False}
                else:
                    checkpoint.plan = rep.payload
                record_step(
                    7,
                    self.planner.name,
                    rep.status if rep.status != StepStatus.ERROR else StepStatus.DEGRADED,
                    True,
                    0,
                    f"Plan built with {len(checkpoint.plan.get('steps', []))} step(s); est_tokens={checkpoint.plan.get('estimated_tokens', 0)}",
                    checkpoint.plan,
                    rep.duration_ms,
                )
                check_crash(7)

            # Step 8: Predict Outcomes
            if checkpoint.current_step < 8:
                rep = self._run_organ_isolated(
                    self.world_model,
                    {"phase": "predict", "plan": checkpoint.plan, "perception": checkpoint.perception_data},
                    simulate_fault_organ,
                )
                if rep.status == StepStatus.ERROR:
                    degraded_organs.append(self.world_model.name)
                    checkpoint.prediction = {"expected_status": "ok", "expected_deterministic": True}
                else:
                    checkpoint.prediction = rep.payload
                record_step(
                    8,
                    self.world_model.name,
                    rep.status if rep.status != StepStatus.ERROR else StepStatus.DEGRADED,
                    True,
                    0,
                    f"Predicted status={checkpoint.prediction.get('expected_status')}, deterministic={checkpoint.prediction.get('expected_deterministic')}",
                    checkpoint.prediction,
                    rep.duration_ms,
                )
                check_crash(8)

            # Step 9: Evaluate Uncertainty, Cost & Risk (Immunity)
            if checkpoint.current_step < 9:
                rep = self._run_organ_isolated(
                    self.immunity,
                    {
                        "cycle_id": checkpoint.cycle_id,
                        "perception": checkpoint.perception_data,
                        "plan": checkpoint.plan,
                        "approved_by_human": approved_by_human,
                        "mode": checkpoint.mode,
                    },
                    simulate_fault_organ,
                )
                if rep.status == StepStatus.ERROR:
                    return self._fail_safe(checkpoint, event, rep.error or "Critical immunity organ failure")
                checkpoint.risk_assessment = rep.payload
                record_step(
                    9,
                    self.immunity.name,
                    rep.status,
                    True,
                    0,
                    f"Risk screen: blocked={rep.payload.get('blocked')}, budget_ok={rep.payload.get('budget_ok')}",
                    rep.payload,
                    rep.duration_ms,
                )
                check_crash(9)

            # Step 10: Executive Decision
            if checkpoint.current_step < 10:
                rep = self._run_organ_isolated(
                    self.executive,
                    {
                        "risk_assessment": checkpoint.risk_assessment,
                        "plan": checkpoint.plan,
                        "approved_by_human": approved_by_human,
                    },
                    simulate_fault_organ,
                )
                if rep.status == StepStatus.ERROR:
                    return self._fail_safe(checkpoint, event, rep.error or "Critical executive organ failure")
                checkpoint.executive_decision = rep.payload
                record_step(
                    10,
                    self.executive.name,
                    rep.status,
                    True,
                    0,
                    f"Decision={rep.payload.get('decision')} -> target={rep.payload.get('target_outcome')}",
                    rep.payload,
                    rep.duration_ms,
                )
                check_crash(10)

            decision_code = checkpoint.executive_decision.get("decision", "ACT_DETERMINISTIC")

            # Early terminal handling for ABORT_SAFE / WAIT_APPROVAL / DEFER_QUOTA
            if decision_code == "ABORT_SAFE":
                reason = checkpoint.executive_decision.get("rationale", "Blocked by safety boundary")
                return self._complete_early_terminal(
                    checkpoint, event, CycleStatus.FAILED_SAFE, reason, degraded_organs
                )
            if decision_code == "WAIT_APPROVAL":
                reason = checkpoint.executive_decision.get("rationale", "Awaiting human approval")
                return self._complete_early_terminal(
                    checkpoint, event, CycleStatus.WAITING, reason, degraded_organs
                )
            if decision_code == "DEFER_QUOTA":
                reason = checkpoint.executive_decision.get("rationale", "Token quota exhausted")
                self.event_bus.defer_event(event, reason=reason, delay_seconds=300)
                return self._complete_early_terminal(
                    checkpoint, event, CycleStatus.DEFERRED, reason, degraded_organs
                )

            # Step 11: Execute Permitted Operation
            if checkpoint.current_step < 11:
                rep = self._run_organ_isolated(
                    self.reasoning,
                    {
                        "perception": checkpoint.perception_data,
                        "retrieved_memories": checkpoint.retrieved_memories,
                        "workspace_items": checkpoint.workspace_snapshot,
                        "active_goal": checkpoint.active_goal,
                        "mode": checkpoint.mode,
                    },
                    simulate_fault_organ,
                )
                if rep.status == StepStatus.BLOCKED:
                    reason = rep.error or "Operation deferred due to quota"
                    self.event_bus.defer_event(event, reason=reason, delay_seconds=300)
                    record_step(11, self.reasoning.name, StepStatus.BLOCKED, True, 0, reason, rep.payload, rep.duration_ms)
                    return self._complete_early_terminal(
                        checkpoint, event, CycleStatus.DEFERRED, reason, degraded_organs
                    )
                if rep.status == StepStatus.ERROR:
                    return self._fail_safe(checkpoint, event, rep.error or "Reasoning organ critical error")

                checkpoint.action_result = {
                    "status": rep.status.value,
                    "confidence": rep.confidence,
                    "deterministic": rep.deterministic,
                    "tokens_used": rep.tokens_used,
                    "payload": rep.payload,
                    "error": rep.error,
                }
                record_step(
                    11,
                    self.reasoning.name,
                    rep.status,
                    rep.deterministic,
                    rep.tokens_used,
                    str(rep.payload.get("answer", ""))[:180],
                    checkpoint.action_result,
                    rep.duration_ms,
                )
                check_crash(11)

            # Step 12: Observe Result
            if checkpoint.current_step < 12:
                rep = self._run_organ_isolated(
                    self.communication,
                    {
                        "reasoning_report": checkpoint.action_result,
                        "executive_decision": checkpoint.executive_decision,
                    },
                    simulate_fault_organ,
                )
                if rep.status == StepStatus.ERROR:
                    degraded_organs.append(self.communication.name)
                record_step(
                    12,
                    self.communication.name,
                    rep.status if rep.status != StepStatus.ERROR else StepStatus.DEGRADED,
                    True,
                    0,
                    f"Observed status={checkpoint.action_result.get('status')}",
                    rep.payload,
                    rep.duration_ms,
                )
                check_crash(12)

            # Step 13: Compare Result with Prediction
            if checkpoint.current_step < 13:
                rep = self._run_organ_isolated(
                    self.world_model,
                    {
                        "phase": "compare",
                        "prediction": checkpoint.prediction,
                        "observed": checkpoint.action_result,
                    },
                    simulate_fault_organ,
                )
                if rep.status == StepStatus.ERROR:
                    degraded_organs.append(self.world_model.name)
                    checkpoint.comparison = {"matched_prediction": False, "prediction_error": 0.5}
                else:
                    checkpoint.comparison = rep.payload
                record_step(
                    13,
                    self.world_model.name,
                    rep.status if rep.status != StepStatus.ERROR else StepStatus.DEGRADED,
                    True,
                    0,
                    f"Prediction matched={checkpoint.comparison.get('matched_prediction')}, error={checkpoint.comparison.get('prediction_error')}",
                    checkpoint.comparison,
                    rep.duration_ms,
                )
                check_crash(13)

            # Step 14: Update World & Metacognitive State
            if checkpoint.current_step < 14:
                rep = self._run_organ_isolated(
                    self.metacognition,
                    {
                        "prior_metacognition": identity.get("metacognition", {}),
                        "comparison": checkpoint.comparison,
                        "reasoning_report": {
                            "confidence": checkpoint.action_result.get("confidence", 0.5),
                            "epistemic_type": checkpoint.action_result.get("payload", {}).get("epistemic_type", "unknown"),
                        },
                        "degraded_organs": degraded_organs,
                    },
                    simulate_fault_organ,
                )
                if rep.status == StepStatus.ERROR:
                    degraded_organs.append(self.metacognition.name)
                    checkpoint.metacognition = identity.get("metacognition", {})
                else:
                    checkpoint.metacognition = rep.payload
                record_step(
                    14,
                    self.metacognition.name,
                    rep.status if rep.status != StepStatus.ERROR else StepStatus.DEGRADED,
                    True,
                    0,
                    f"Calibration={checkpoint.metacognition.get('calibration_score')}, gap={checkpoint.metacognition.get('knowledge_gap_detected')}",
                    checkpoint.metacognition,
                    rep.duration_ms,
                )
                check_crash(14)

            # Step 15: Record Episodic Event & Checkpoint
            episode_id = ""
            if checkpoint.current_step < 15:
                answer = str(checkpoint.action_result.get("payload", {}).get("answer", "Completed cycle"))
                ep_rep = self._run_organ_isolated(
                    self.episodic_memory,
                    {
                        "cycle_id": checkpoint.cycle_id,
                        "event_id": event.event_id,
                        "source": event.source,
                        "trust_level": event.trust_level.value,
                        "event_content": event.content,
                        "action_taken": checkpoint.executive_decision.get("decision", "ACT"),
                        "outcome_status": CycleStatus.COMPLETED.value,
                        "outcome_summary": answer,
                        "metadata": {
                            "tokens_used": checkpoint.tokens_used,
                            "degraded_organs": degraded_organs,
                            "epistemic_type": checkpoint.action_result.get("payload", {}).get("epistemic_type", "unknown"),
                        },
                    },
                    simulate_fault_organ,
                )
                if ep_rep.status == StepStatus.ERROR:
                    return self._fail_safe(checkpoint, event, ep_rep.error or "Critical episodic persistence failure")
                episode_id = str(ep_rep.payload["episode_id"])
                checkpoint.outcome_summary = answer
                record_step(
                    15,
                    self.episodic_memory.name,
                    StepStatus.OK,
                    True,
                    0,
                    f"Recorded provenance episode '{episode_id}'",
                    {"episode_id": episode_id},
                    ep_rep.duration_ms,
                )
                check_crash(15)

            # Step 16: Consolidate into Long-Term Memory
            if checkpoint.current_step < 16:
                rep = self._run_organ_isolated(
                    self.learning,
                    {
                        "episode_id": episode_id,
                        "reasoning_payload": checkpoint.action_result.get("payload", {}),
                        "perception": checkpoint.perception_data,
                        "outcome_status": CycleStatus.COMPLETED.value,
                    },
                    simulate_fault_organ,
                )
                if rep.status == StepStatus.ERROR:
                    degraded_organs.append(self.learning.name)

                CycleStateMachine.validate_status_transition(checkpoint.status, CycleStatus.COMPLETED)
                checkpoint.status = CycleStatus.COMPLETED
                record_step(
                    16,
                    self.learning.name,
                    rep.status if rep.status != StepStatus.ERROR else StepStatus.DEGRADED,
                    True,
                    0,
                    f"Consolidated {rep.payload.get('consolidated_count', 0)} durable memory assertion(s)",
                    rep.payload,
                    rep.duration_ms,
                )

            # Update persistent identity, idempotency, and resolve deferred queue if applicable
            self.store.update_identity_metrics(
                increment_cycles=1,
                homeostasis=checkpoint.homeostasis,
                metacognition=checkpoint.metacognition,
            )
            self.store.record_idempotency(
                event.operation_id,
                checkpoint.cycle_id,
                CycleStatus.COMPLETED,
                checkpoint.outcome_summary,
            )
            self.store.mark_deferred_resolved(event.operation_id)
            self.store.export_snapshot()
            self.event_bus.publish("cycle.completed", {"cycle_id": checkpoint.cycle_id})
            return checkpoint

        except SimulatedCrashInterrupt as exc:
            checkpoint.error_message = str(exc)
            self.store.save_checkpoint(checkpoint)
            return checkpoint

    def _complete_early_terminal(
        self,
        checkpoint: CycleCheckpoint,
        event: CognitiveEvent,
        target_status: CycleStatus,
        reason: str,
        degraded_organs: list[str],
    ) -> CycleCheckpoint:
        CycleStateMachine.validate_status_transition(checkpoint.status, target_status)
        checkpoint.status = target_status
        checkpoint.outcome_summary = reason
        if target_status == CycleStatus.FAILED_SAFE:
            checkpoint.error_message = reason

        self.store.insert_episode(
            cycle_id=checkpoint.cycle_id,
            event_id=event.event_id,
            source=event.source,
            trust_level=event.trust_level.value,
            event_content=event.content,
            action_taken=checkpoint.executive_decision.get("decision", target_status.value),
            outcome_status=target_status.value,
            outcome_summary=reason,
            metadata={"degraded_organs": degraded_organs, "halted_at_step": checkpoint.current_step},
        )
        self.store.update_identity_metrics(increment_cycles=1)
        if target_status == CycleStatus.FAILED_SAFE:
            self.store.record_idempotency(
                event.operation_id, checkpoint.cycle_id, target_status, reason
            )
        self.store.save_checkpoint(checkpoint)
        return checkpoint

    def _fail_safe(
        self,
        checkpoint: CycleCheckpoint,
        event: CognitiveEvent,
        reason: str,
    ) -> CycleCheckpoint:
        return self._complete_early_terminal(
            checkpoint=checkpoint,
            event=event,
            target_status=CycleStatus.FAILED_SAFE,
            reason=reason,
            degraded_organs=[],
        )

    def get_full_state(self) -> dict[str, Any]:
        return {
            "identity": self.store.get_identity(),
            "model_config": {
                "provider": self.config.model_provider,
                "model_name": self.config.model_name,
                "gemini_configured": self.provider.is_configured(),
                "workspace_capacity": self.config.workspace_capacity,
                "working_memory_capacity": self.config.working_memory_capacity,
            },
            "budget_today": self.budget.get_today_totals(),
            "usage_ledger": self.store.list_usage_ledger(limit=14),
            "checkpoints": self.store.list_checkpoints(limit=25),
            "episodes": self.store.list_episodes(limit=40),
            "semantic_facts": self.store.list_semantic_facts(include_invalidated=True, limit=60),
            "kg_edges": self.store.list_kg_edges(limit=50),
            "working_memory": self.store.list_working_memory(),
            "procedures": self.store.list_procedures(),
            "deferred_queue": self.store.list_deferred(),
            "safety_audits": self.store.list_safety_audits(limit=40),
            "evaluation_runs": self.store.list_evaluation_runs(limit=10),
            "snapshot_integrity_valid": self.store.verify_snapshot_file(),
        }
