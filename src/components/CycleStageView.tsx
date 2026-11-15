import { useState } from "react";
import type { CycleCheckpoint, WorldTransition, WorkingMemorySlot } from "../types";
import { StatusGlyph, StepStatusText } from "./StatusGlyph";

const ALL_CYCLE_STEPS = [
  { num: 1, name: "Receive Event", organ: "scheduler" },
  { num: 2, name: "Perceive & Classify", organ: "perception" },
  { num: 3, name: "Retrieve Memories", organ: "memory_retrieval" },
  { num: 4, name: "Evaluate Attention", organ: "attention" },
  { num: 5, name: "Update Workspace", organ: "workspace" },
  { num: 6, name: "Identify Goals & Constraints", organ: "motivation" },
  { num: 7, name: "Construct Plan", organ: "planner" },
  { num: 8, name: "Predict Outcomes", organ: "world_model" },
  { num: 9, name: "Evaluate Uncertainty & Risk", organ: "immunity" },
  { num: 10, name: "Executive Decision", organ: "executive" },
  { num: 11, name: "Execute Permitted Operation", organ: "reasoning" },
  { num: 12, name: "Observe Result", organ: "communication" },
  { num: 13, name: "Compare Prediction vs Result", organ: "world_model" },
  { num: 14, name: "Update World & Metacognition", organ: "metacognition" },
  { num: 15, name: "Record Event & Checkpoint", organ: "episodic_memory" },
  { num: 16, name: "Consolidate Memory", organ: "learning" },
];

interface Props {
  checkpoints: CycleCheckpoint[];
  workingMemory: WorkingMemorySlot[];
  worldTransitions: WorldTransition[];
  workspaceCapacity: number;
  workingCapacity: number;
  selectedCycleId: string | null;
  onSelectCycle: (id: string) => void;
  onResumeCycle: (cycleId: string) => void;
  onApproveCycle: (cycleId: string, decision: "approve" | "reject") => void;
  busy: boolean;
}

export function CycleStageView({
  checkpoints,
  workingMemory,
  worldTransitions,
  workspaceCapacity,
  workingCapacity,
  selectedCycleId,
  onSelectCycle,
  onResumeCycle,
  onApproveCycle,
  busy,
}: Props) {
  const activeCheckpoint =
    checkpoints.find((c) => c.cycle_id === selectedCycleId) || checkpoints[0] || null;
  const [selectedStepNum, setSelectedStepNum] = useState<number | null>(null);

  if (!activeCheckpoint) {
    return (
      <div className="bg-white border border-slate-200 rounded-lg p-8">
        <h2 className="text-lg font-semibold text-slate-900">
          No Cognitive Cycles Recorded Yet
        </h2>
        <p className="mt-2 text-sm text-slate-600 max-w-2xl">
          ORGANISM starts from a clean persistent SQLite state. Choose a stimulus preset in
          the left control rail or enter an event, then execute a wake cycle to inspect all
          16 deterministic and model-assisted steps, adaptive world-model posteriors, and
          Brier score calibration.
        </p>
      </div>
    );
  }

  const traceByNum = new Map(activeCheckpoint.step_traces.map((t) => [t.step_number, t]));
  const activeStepTrace =
    (selectedStepNum ? traceByNum.get(selectedStepNum) : null) ||
    activeCheckpoint.step_traces[activeCheckpoint.step_traces.length - 1] ||
    null;

  const pred = activeCheckpoint.prediction || {};
  const comp = activeCheckpoint.comparison || {};
  const mc = activeCheckpoint.metacognition || {};
  const axes = (mc.confidence_axes || {}) as Record<string, number | undefined>;
  const refrainRecommended = Boolean(mc.refrain_recommended);
  const refrainReasons = Array.isArray(mc.refrain_reasons) ? mc.refrain_reasons.map(String) : [];

  return (
    <div className="space-y-6">
      {/* Cycle selector & summary header */}
      <div className="bg-white border border-slate-200 rounded-lg p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500 font-mono tabular-nums">
              <span>{activeCheckpoint.cycle_id}</span>
              <span aria-hidden="true">·</span>
              <span>op:{activeCheckpoint.operation_id}</span>
              <span aria-hidden="true">·</span>
              <span>step {activeCheckpoint.current_step}/16</span>
              <span aria-hidden="true">·</span>
              <span>{activeCheckpoint.tokens_used} tokens</span>
            </div>
            <h2 className="mt-2 text-lg font-semibold text-slate-900 break-words">
              {activeCheckpoint.event_payload?.content || "Wake Cycle"}
            </h2>
            <p className="mt-1.5 text-sm text-slate-700">
              {activeCheckpoint.outcome_summary ||
                activeCheckpoint.error_message ||
                "Cycle paused mid-execution with recoverable checkpoint."}
            </p>
          </div>

          <div className="flex flex-col items-end gap-2 shrink-0">
            <StatusGlyph status={activeCheckpoint.status} />
            <div className="flex items-center gap-2">
              {activeCheckpoint.status === "RUNNING" && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onResumeCycle(activeCheckpoint.cycle_id)}
                  className="px-3 py-1.5 text-xs font-medium bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 whitespace-nowrap shrink-0"
                >
                  Resume From Step {activeCheckpoint.current_step + 1}
                </button>
              )}
              {activeCheckpoint.status === "WAITING" && (
                <>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => onApproveCycle(activeCheckpoint.cycle_id, "approve")}
                    className="px-3 py-1.5 text-xs font-medium bg-emerald-700 text-white rounded-md hover:bg-emerald-800 disabled:opacity-50 whitespace-nowrap shrink-0"
                  >
                    Approve Action
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => onApproveCycle(activeCheckpoint.cycle_id, "reject")}
                    className="px-3 py-1.5 text-xs font-medium bg-white border border-slate-300 text-slate-700 rounded-md hover:bg-slate-50 disabled:opacity-50 whitespace-nowrap shrink-0"
                  >
                    Reject
                  </button>
                </>
              )}
            </div>
          </div>
        </div>

        {/* Stage 2 Adaptive World Model & Metacognition Telemetry Strip */}
        <div className="mt-5 pt-4 border-t border-slate-200 grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="p-3.5 bg-slate-50 border border-slate-200 rounded-md">
            <div className="flex items-center justify-between text-xs">
              <span className="font-medium text-slate-700">World Model Posterior</span>
              <span className="font-mono text-slate-500 tabular-nums">
                {String(pred.model_source || "dirichlet_prior")} · {Number(pred.sample_count ?? 0)} obs
              </span>
            </div>
            <div className="mt-2 grid grid-cols-3 gap-2 text-xs font-mono tabular-nums">
              <div>
                <span className="text-slate-400 block">P(expected)</span>
                <span className="text-slate-900 font-semibold">
                  {pred.predicted_probability !== undefined
                    ? `${(Number(pred.predicted_probability) * 100).toFixed(1)}%`
                    : "—"}
                </span>
              </div>
              <div>
                <span className="text-slate-400 block">Entropy H</span>
                <span className="text-slate-900 font-semibold">
                  {pred.transition_entropy !== undefined
                    ? Number(pred.transition_entropy).toFixed(2)
                    : "—"}
                </span>
              </div>
              <div>
                <span className="text-slate-400 block">TD Error</span>
                <span className="text-slate-900 font-semibold">
                  {comp.td_error !== undefined ? Number(comp.td_error).toFixed(3) : "—"}
                </span>
              </div>
            </div>
          </div>

          <div className="p-3.5 bg-slate-50 border border-slate-200 rounded-md">
            <div className="flex items-center justify-between text-xs">
              <span className="font-medium text-slate-700">Metacognitive Calibration</span>
              <span
                className={`font-mono tabular-nums ${
                  refrainRecommended ? "text-amber-700 font-semibold" : "text-emerald-700"
                }`}
              >
                {refrainRecommended ? "▲ ABSTAIN ADVISED" : "● CALIBRATED"} · Brier{" "}
                {mc.brier_score !== undefined ? Number(mc.brier_score).toFixed(3) : "0.000"}
              </span>
            </div>
            <div className="mt-2 grid grid-cols-4 gap-2 text-xs font-mono tabular-nums">
              <div>
                <span className="text-slate-400 block">Pred</span>
                <span className="text-slate-900 font-semibold">
                  {axes.prediction_confidence !== undefined
                    ? Number(axes.prediction_confidence).toFixed(2)
                    : "—"}
                </span>
              </div>
              <div>
                <span className="text-slate-400 block">Source</span>
                <span className="text-slate-900 font-semibold">
                  {axes.source_confidence !== undefined
                    ? Number(axes.source_confidence).toFixed(2)
                    : "—"}
                </span>
              </div>
              <div>
                <span className="text-slate-400 block">Memory</span>
                <span className="text-slate-900 font-semibold">
                  {axes.memory_confidence !== undefined
                    ? Number(axes.memory_confidence).toFixed(2)
                    : "—"}
                </span>
              </div>
              <div>
                <span className="text-slate-400 block">Reason</span>
                <span className="text-slate-900 font-semibold">
                  {axes.reasoning_confidence !== undefined
                    ? Number(axes.reasoning_confidence).toFixed(2)
                    : "—"}
                </span>
              </div>
            </div>
            {refrainRecommended && refrainReasons.length > 0 && (
              <div className="mt-2 text-xs font-mono text-amber-700">
                Reason: {refrainReasons.join(", ")}
              </div>
            )}
          </div>
        </div>

        {/* Recent cycles switcher */}
        {checkpoints.length > 1 && (
          <div className="mt-4 pt-4 border-t border-slate-200 flex items-center gap-2 overflow-x-auto">
            <span className="text-xs font-medium text-slate-500 whitespace-nowrap shrink-0 mr-1">
              Recent Cycles:
            </span>
            {checkpoints.slice(0, 6).map((cp) => {
              const isSelected = cp.cycle_id === activeCheckpoint.cycle_id;
              return (
                <button
                  key={cp.cycle_id}
                  type="button"
                  onClick={() => {
                    onSelectCycle(cp.cycle_id);
                    setSelectedStepNum(null);
                  }}
                  className={`px-2.5 py-1 text-xs font-mono tabular-nums rounded-md border transition-colors whitespace-nowrap shrink-0 ${
                    isSelected
                      ? "bg-slate-900 text-white border-slate-900"
                      : "bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100"
                  }`}
                >
                  {cp.cycle_id.slice(0, 11)} · {cp.status}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* 16-Step Trace Table + Organ Contract Inspector */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
        <div className="xl:col-span-7 bg-white border border-slate-200 rounded-lg overflow-hidden">
          <div className="px-5 py-3.5 border-b border-slate-200 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-900">
              16-Step Cognitive Cycle State Machine
            </h3>
            <span className="text-xs text-slate-500 font-mono tabular-nums">
              Click a step to inspect organ output
            </span>
          </div>
          <div className="divide-y divide-slate-100">
            {ALL_CYCLE_STEPS.map((spec) => {
              const trace = traceByNum.get(spec.num);
              const isSelected = activeStepTrace?.step_number === spec.num;
              return (
                <button
                  key={spec.num}
                  type="button"
                  disabled={!trace}
                  onClick={() => trace && setSelectedStepNum(spec.num)}
                  className={`w-full text-left px-5 py-2.5 flex items-center justify-between gap-3 transition-colors ${
                    isSelected
                      ? "bg-blue-50/70"
                      : trace
                      ? "hover:bg-slate-50"
                      : "opacity-45 cursor-default"
                  }`}
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <span className="font-mono text-xs tabular-nums text-slate-400 w-6 shrink-0">
                      {String(spec.num).padStart(2, "0")}
                    </span>
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-slate-900 truncate">
                        {spec.name}
                      </div>
                      <div className="text-xs text-slate-500 truncate">
                        {trace ? trace.summary : `Organ: ${spec.organ} · Pending`}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    {trace && (
                      <>
                        <span className="font-mono text-xs text-slate-500 tabular-nums">
                          {trace.deterministic ? "DET" : `LLM ${trace.tokens_used}t`}
                        </span>
                        <StepStatusText status={trace.status} />
                      </>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Right inspector: Active Step Contract + Learned World Transitions + Workspace */}
        <div className="xl:col-span-5 space-y-6">
          <div className="bg-white border border-slate-200 rounded-lg p-5">
            <div className="flex items-center justify-between gap-2 pb-3 border-b border-slate-200">
              <h3 className="text-sm font-semibold text-slate-900">
                Organ Contract Inspection
              </h3>
              {activeStepTrace && (
                <span className="font-mono text-xs text-slate-500 tabular-nums">
                  Step {activeStepTrace.step_number} · {activeStepTrace.organ} ·{" "}
                  {activeStepTrace.duration_ms.toFixed(1)} ms
                </span>
              )}
            </div>
            {activeStepTrace ? (
              <div className="mt-3 space-y-3">
                <p className="text-xs text-slate-600">{activeStepTrace.summary}</p>
                <pre className="bg-slate-50 border border-slate-200 rounded-md p-3 text-xs font-mono text-slate-800 overflow-x-auto max-h-72 overflow-y-auto">
                  {JSON.stringify(activeStepTrace.data, null, 2)}
                </pre>
              </div>
            ) : (
              <p className="mt-3 text-xs text-slate-500">
                Select an executed step to view its structured contract payload.
              </p>
            )}
          </div>

          <div className="bg-white border border-slate-200 rounded-lg p-5">
            <div className="flex items-center justify-between pb-3 border-b border-slate-200">
              <h3 className="text-sm font-semibold text-slate-900">
                Learned World-Model Transitions
              </h3>
              <span className="font-mono text-xs text-slate-500 tabular-nums">
                {worldTransitions.length} state-action(s)
              </span>
            </div>
            {worldTransitions.length === 0 ? (
              <p className="mt-3 text-xs text-slate-500">
                No transition posteriors learned yet.
              </p>
            ) : (
              <ul className="mt-3 divide-y divide-slate-100">
                {worldTransitions.slice(0, 5).map((tr) => {
                  const total = Object.values(tr.alpha_counts || {}).reduce((a, b) => a + b, 0);
                  const pOk = total > 0 ? ((tr.alpha_counts?.ok || 0) / total) * 100 : 0;
                  return (
                    <li key={tr.state_action_key} className="py-2 text-xs">
                      <div className="font-mono text-slate-800 truncate">{tr.state_action_key}</div>
                      <div className="mt-0.5 flex items-center justify-between text-slate-500 font-mono tabular-nums">
                        <span>
                          n={tr.sample_count} · P(ok)={pOk.toFixed(0)}%
                        </span>
                        <span>
                          TD_ema={tr.td_error_ema.toFixed(3)} · Fisher={tr.fisher_precision.toFixed(2)}
                        </span>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <div className="bg-white border border-slate-200 rounded-lg p-5">
            <div className="flex items-center justify-between pb-3 border-b border-slate-200">
              <h3 className="text-sm font-semibold text-slate-900">
                Global Cognitive Workspace
              </h3>
              <span className="font-mono text-xs text-slate-500 tabular-nums">
                {activeCheckpoint.workspace_snapshot.length} / {workspaceCapacity} slots
              </span>
            </div>
            {activeCheckpoint.workspace_snapshot.length === 0 ? (
              <p className="mt-3 text-xs text-slate-500">Workspace empty for this cycle.</p>
            ) : (
              <ul className="mt-3 divide-y divide-slate-100">
                {activeCheckpoint.workspace_snapshot.map((item) => (
                  <li key={item.slot} className="py-2 text-xs">
                    <div className="flex items-center justify-between text-slate-500 font-mono tabular-nums">
                      <span>
                        Slot {item.slot} · {item.layer} · {item.epistemic_type}
                      </span>
                      <span>salience {item.salience.toFixed(2)}</span>
                    </div>
                    <p className="mt-1 text-slate-800">{item.summary}</p>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="bg-white border border-slate-200 rounded-lg p-5">
            <div className="flex items-center justify-between pb-3 border-b border-slate-200">
              <h3 className="text-sm font-semibold text-slate-900">Working Memory</h3>
              <span className="font-mono text-xs text-slate-500 tabular-nums">
                {workingMemory.length} / {workingCapacity} slots
              </span>
            </div>
            {workingMemory.length === 0 ? (
              <p className="mt-3 text-xs text-slate-500">No active working memory slots.</p>
            ) : (
              <ul className="mt-3 divide-y divide-slate-100">
                {workingMemory.slice(0, 6).map((slot) => (
                  <li key={slot.slot_id} className="py-2 text-xs">
                    <div className="flex items-center justify-between text-slate-500 font-mono tabular-nums">
                      <span className="truncate">{slot.key}</span>
                      <span>
                        p={slot.priority.toFixed(2)} · ttl c{slot.expires_at_cycle}
                      </span>
                    </div>
                    <p className="mt-0.5 text-slate-800 truncate font-mono">
                      {JSON.stringify(slot.value)}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
