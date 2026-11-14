import type { EvaluationRun, SafetyAuditEntry } from "../types";

interface Props {
  safetyAudits: SafetyAuditEntry[];
  evaluationRuns: EvaluationRun[];
  latestUnitOutput: { ok: boolean; output: string } | null;
  onRunEvaluation: () => void;
  runningEval: boolean;
}

export function SafetyTestsView({
  safetyAudits,
  evaluationRuns,
  latestUnitOutput,
  onRunEvaluation,
  runningEval,
}: Props) {
  const latestEval = evaluationRuns[0] || null;

  return (
    <div className="space-y-6">
      {/* Automated Evaluation & Benchmark Runner */}
      <div className="bg-white border border-slate-200 rounded-lg p-6">
        <div className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-slate-200">
          <div>
            <h2 className="text-base font-semibold text-slate-900">
              Automated Verification & Capability Benchmarks
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Executes the real Python unit test suite and Stage 1 baseline checks against isolated SQLite state
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
                <div className="text-xs text-slate-500">Baseline Score</div>
                <div className="mt-1 text-xl font-mono font-semibold text-slate-900 tabular-nums">
                  {(latestEval.metrics.score * 100).toFixed(0)}%
                </div>
              </div>
              <div className="p-3.5 bg-slate-50 border border-slate-200 rounded-md">
                <div className="text-xs text-slate-500">Checks Passed</div>
                <div className="mt-1 text-xl font-mono font-semibold text-emerald-700 tabular-nums">
                  {latestEval.passed} / {latestEval.total}
                </div>
              </div>
              <div className="p-3.5 bg-slate-50 border border-slate-200 rounded-md">
                <div className="text-xs text-slate-500">Failed Checks</div>
                <div className="mt-1 text-xl font-mono font-semibold text-slate-900 tabular-nums">
                  {latestEval.failed}
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
                  <span className="text-slate-700">{name}</span>
                  <span className={ok ? "text-emerald-700" : "text-rose-700"}>
                    {ok ? "● PASS" : "✖ FAIL"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <p className="mt-4 text-sm text-slate-500">
            No benchmark run persisted yet. Click <strong>Run Evaluation Suite</strong> to verify all Stage 1 invariants.
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

      {/* Immunity & Safety Audit Log */}
      <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-200">
          <h3 className="text-sm font-semibold text-slate-900">
            Immunity & Safety Audit Log
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
