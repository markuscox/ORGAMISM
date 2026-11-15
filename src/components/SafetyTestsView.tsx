import type {
  EvaluationRun,
  OrganMetric,
  ReplayExperience,
  SafetyAuditEntry,
} from "../types";

interface Props {
  safetyAudits: SafetyAuditEntry[];
  evaluationRuns: EvaluationRun[];
  organMetrics: OrganMetric[];
  replayBuffer: ReplayExperience[];
  latestUnitOutput: { ok: boolean; output: string } | null;
  onRunEvaluation: () => void;
  onRunReplay: () => void;
  runningEval: boolean;
  busy: boolean;
}

export function SafetyTestsView({
  safetyAudits,
  evaluationRuns,
  organMetrics,
  replayBuffer,
  latestUnitOutput,
  onRunEvaluation,
  onRunReplay,
  runningEval,
  busy,
}: Props) {
  const latestEval = evaluationRuns[0] || null;
  const hist = latestEval?.metrics?.historical_comparison;
  const delta = hist?.score_delta;
  const brier = latestEval?.metrics?.brier_score;

  return (
    <div className="space-y-6">
      {/* Automated Evaluation & Benchmark Runner */}
      <div className="bg-white border border-slate-200 rounded-lg p-6">
        <div className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-slate-200">
          <div>
            <h2 className="text-base font-semibold text-slate-900">
              Automated Verification &amp; Stage 1+2 Capability Benchmarks
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Executes Stage 1 + Stage 2 Python unit tests and cognitive capability benchmarks with historical regression detection
            </p>
          </div>
          <button
            type="button"
            disabled={runningEval}
            onClick={onRunEvaluation}
            className="px-4 py-2 text-xs font-medium bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 whitespace-nowrap shrink-0"
          >
            {runningEval ? "Running Suite..." : "Run Evaluation Suite"}
          </button>
        </div>

        {latestEval ? (
          <div className="mt-5 space-y-5">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              <div className="p-3.5 bg-slate-50 border border-slate-200 rounded-md">
                <div className="text-xs text-slate-500">Combined Score</div>
                <div className="mt-1 text-xl font-mono font-semibold text-slate-900 tabular-nums">
                  {(latestEval.metrics.score * 100).toFixed(0)}%
                </div>
                {delta !== undefined && delta !== null && (
                  <div className="mt-0.5 text-xs font-mono text-slate-500 tabular-nums">
                    delta {delta >= 0 ? `+${(delta * 100).toFixed(1)}%` : `${(delta * 100).toFixed(1)}%`}
                  </div>
                )}
              </div>
              <div className="p-3.5 bg-slate-50 border border-slate-200 rounded-md">
                <div className="text-xs text-slate-500">Checks Passed</div>
                <div className="mt-1 text-xl font-mono font-semibold text-emerald-700 tabular-nums">
                  {latestEval.passed} / {latestEval.total}
                </div>
                {brier !== undefined && (
                  <div className="mt-0.5 text-xs font-mono text-slate-500 tabular-nums">
                    Brier {Number(brier).toFixed(4)}
                  </div>
                )}
              </div>
              <div className="p-3.5 bg-slate-50 border border-slate-200 rounded-md">
                <div className="text-xs text-slate-500">Regression Status</div>
                <div
                  className={`mt-1 text-base font-mono font-semibold tabular-nums ${
                    hist?.regression_detected ? "text-rose-700" : "text-emerald-700"
                  }`}
                >
                  {hist?.regression_detected ? "▲ REGRESSION" : "● CLEAR"}
                </div>
                <div className="mt-0.5 text-xs font-mono text-slate-500 tabular-nums">
                  failed checks: {latestEval.failed}
                </div>
              </div>
              <div className="p-3.5 bg-slate-50 border border-slate-200 rounded-md">
                <div className="text-xs text-slate-500">LLM Calls Used</div>
                <div className="mt-1 text-xl font-mono font-semibold text-slate-900 tabular-nums">
                  {latestEval.metrics.llm_calls_during_benchmark ?? 0}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
              {Object.entries(latestEval.metrics.checks || {}).map(([name, ok]) => (
                <div
                  key={name}
                  className="flex items-center justify-between px-3.5 py-2 border border-slate-200 rounded-md text-xs font-mono"
                >
                  <span className="text-slate-700 truncate mr-2">{name}</span>
                  <span className={ok ? "text-emerald-700 shrink-0" : "text-rose-700 shrink-0"}>
                    {ok ? "● PASS" : "✖ FAIL"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <p className="mt-4 text-sm text-slate-500">
            No benchmark run persisted yet. Click <strong>Run Evaluation Suite</strong> to verify all Stage 1 and Stage 2 invariants.
          </p>
        )}

        {latestUnitOutput && (
          <div className="mt-5 pt-4 border-t border-slate-200">
            <div className="flex items-center justify-between text-xs font-mono mb-2">
              <span className="text-slate-700 font-medium">
                Python Unittest Runner Output
              </span>
              <span className={latestUnitOutput.ok ? "text-emerald-700" : "text-rose-700"}>
                {latestUnitOutput.ok ? "● ALL TESTS PASSED" : "✖ TEST FAILURE"}
              </span>
            </div>
            <pre className="bg-slate-50 border border-slate-200 rounded-md p-3 text-xs font-mono text-slate-800 overflow-x-auto max-h-60 overflow-y-auto">
              {latestUnitOutput.output}
            </pre>
          </div>
        )}
      </div>

      {/* Longitudinal Evaluation History */}
      {evaluationRuns.length > 0 && (
        <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-200">
            <h3 className="text-sm font-semibold text-slate-900">
              Longitudinal Benchmark History
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Historical score progression and regression comparisons across evaluation runs
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-xs font-medium text-slate-500">
                  <th className="py-2.5 px-4">Run ID</th>
                  <th className="py-2.5 px-4">Suite</th>
                  <th className="py-2.5 px-4 text-right">Checks</th>
                  <th className="py-2.5 px-4 text-right">Score</th>
                  <th className="py-2.5 px-4 text-right">Delta</th>
                  <th className="py-2.5 px-4">Regression</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-xs font-mono tabular-nums">
                {evaluationRuns.slice(0, 10).map((run) => {
                  const runHist = run.metrics?.historical_comparison;
                  const runDelta = runHist?.score_delta ?? 0;
                  return (
                    <tr key={run.run_id} className="hover:bg-slate-50">
                      <td className="py-2.5 px-4 text-slate-600">{run.run_id}</td>
                      <td className="py-2.5 px-4 text-slate-900">{run.suite_name}</td>
                      <td className="py-2.5 px-4 text-right text-slate-700">
                        {run.passed}/{run.total}
                      </td>
                      <td className="py-2.5 px-4 text-right font-semibold text-slate-900">
                        {(run.metrics.score * 100).toFixed(0)}%
                      </td>
                      <td className="py-2.5 px-4 text-right text-slate-600">
                        {runDelta >= 0 ? `+${(runDelta * 100).toFixed(1)}%` : `${(runDelta * 100).toFixed(1)}%`}
                      </td>
                      <td className="py-2.5 px-4">
                        <span
                          className={
                            runHist?.regression_detected ? "text-rose-700" : "text-emerald-700"
                          }
                        >
                          {runHist?.regression_detected ? "▲ YES" : "● NO"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Continual Learning Replay Buffer & EWC Rehearsal */}
      <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-200 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-slate-900">
              Continual Learning Replay Buffer &amp; EWC Rehearsal
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Prioritized state-action experiences replayed with Fisher precision anchoring to prevent catastrophic forgetting ({replayBuffer.length} buffered)
            </p>
          </div>
          <button
            type="button"
            disabled={busy || replayBuffer.length === 0}
            onClick={onRunReplay}
            className="px-3.5 py-2 text-xs font-medium bg-white border border-slate-300 text-slate-700 rounded-md hover:bg-slate-50 disabled:opacity-50 whitespace-nowrap shrink-0"
          >
            Trigger Replay Rehearsal
          </button>
        </div>
        {replayBuffer.length === 0 ? (
          <div className="p-6 text-sm text-slate-500">
            Replay buffer empty. Complete wake cycles to populate prioritized experience transitions.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-xs font-medium text-slate-500">
                  <th className="py-2.5 px-4">State | Action</th>
                  <th className="py-2.5 px-4">Observed</th>
                  <th className="py-2.5 px-4">Regime</th>
                  <th className="py-2.5 px-4 text-right">Priority</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-xs font-mono tabular-nums">
                {replayBuffer.slice(0, 10).map((row) => (
                  <tr key={row.replay_id} className="hover:bg-slate-50">
                    <td className="py-2.5 px-4 text-slate-900">
                      {row.state_key} | {row.action_key}
                    </td>
                    <td className="py-2.5 px-4 text-slate-700">{row.observed_status}</td>
                    <td className="py-2.5 px-4 text-slate-500">{row.regime_tag}</td>
                    <td className="py-2.5 px-4 text-right text-slate-700">
                      {row.priority.toFixed(3)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Per-Organ Reliability Telemetry */}
      <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-200">
          <h3 className="text-sm font-semibold text-slate-900">
            Organ Reliability &amp; Latency Monitoring
          </h3>
          <p className="text-xs text-slate-500 mt-0.5">
            Longitudinal reliability EMA, fault isolation counts, and average execution time per cognitive organ
          </p>
        </div>
        {organMetrics.length === 0 ? (
          <div className="p-6 text-sm text-slate-500">
            No organ executions recorded yet.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-xs font-medium text-slate-500">
                  <th className="py-2.5 px-4">Organ</th>
                  <th className="py-2.5 px-4 text-right">Runs</th>
                  <th className="py-2.5 px-4 text-right">OK</th>
                  <th className="py-2.5 px-4 text-right">Degraded</th>
                  <th className="py-2.5 px-4 text-right">Errors</th>
                  <th className="py-2.5 px-4 text-right">Avg ms</th>
                  <th className="py-2.5 px-4 text-right">Reliability EMA</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-xs font-mono tabular-nums">
                {organMetrics.map((m) => (
                  <tr key={m.organ_name} className="hover:bg-slate-50">
                    <td className="py-2.5 px-4 text-slate-900 font-medium">{m.organ_name}</td>
                    <td className="py-2.5 px-4 text-right text-slate-700">{m.executions}</td>
                    <td className="py-2.5 px-4 text-right text-emerald-700">{m.successes}</td>
                    <td className="py-2.5 px-4 text-right text-amber-700">{m.degraded_count}</td>
                    <td className="py-2.5 px-4 text-right text-rose-700">{m.error_count}</td>
                    <td className="py-2.5 px-4 text-right text-slate-600">
                      {m.avg_duration_ms.toFixed(2)}
                    </td>
                    <td className="py-2.5 px-4 text-right font-semibold text-slate-900">
                      {(m.reliability_ema * 100).toFixed(1)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Immunity & Safety Audit Log */}
      <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-200">
          <h3 className="text-sm font-semibold text-slate-900">
            Immunity &amp; Safety Audit Log
          </h3>
          <p className="text-xs text-slate-500 mt-0.5">
            Append-only log of prompt-injection blocks, secret redactions, and human approval gates
          </p>
        </div>
        {safetyAudits.length === 0 ? (
          <div className="p-6 text-sm text-slate-500">
            No safety events triggered yet. Test a prompt-injection or high-impact stimulus from the control rail.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-xs font-medium text-slate-500">
                  <th className="py-2.5 px-4">Audit ID</th>
                  <th className="py-2.5 px-4">Severity</th>
                  <th className="py-2.5 px-4">Rule Triggered</th>
                  <th className="py-2.5 px-4">Decision</th>
                  <th className="py-2.5 px-4">Redacted Excerpt</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-xs">
                {safetyAudits.map((row) => (
                  <tr key={row.audit_id} className="hover:bg-slate-50">
                    <td className="py-2.5 px-4 font-mono text-slate-500">{row.audit_id}</td>
                    <td className="py-2.5 px-4 font-mono font-medium text-slate-900">
                      {row.severity}
                    </td>
                    <td className="py-2.5 px-4 font-mono text-slate-700">
                      {row.rule_triggered}
                    </td>
                    <td className="py-2.5 px-4 font-mono text-rose-700">
                      {row.action_decision}
                    </td>
                    <td className="py-2.5 px-4 text-slate-700">{row.excerpt}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
