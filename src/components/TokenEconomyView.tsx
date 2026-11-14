import type { DeferredItem, OrganismFullState, UsageLedgerRow } from "../types";

interface Props {
  budgetToday: OrganismFullState["budget_today"];
  usageLedger: UsageLedgerRow[];
  deferredQueue: DeferredItem[];
  modelConfig: OrganismFullState["model_config"];
  onResumeDeferred: () => void;
  busy: boolean;
}

export function TokenEconomyView({
  budgetToday,
  usageLedger,
  deferredQueue,
  modelConfig,
  onResumeDeferred,
  busy,
}: Props) {
  const tokenPct = Math.min(
    100,
    (budgetToday.total_tokens / Math.max(1, budgetToday.daily_token_limit)) * 100
  );
  const reqPct = Math.min(
    100,
    (budgetToday.requests_used / Math.max(1, budgetToday.daily_request_limit)) * 100
  );
  const totalResolutions = budgetToday.deterministic_resolutions + budgetToday.requests_used;
  const detRatio =
    totalResolutions > 0
      ? ((budgetToday.deterministic_resolutions / totalResolutions) * 100).toFixed(1)
      : "100.0";

  return (
    <div className="space-y-6">
      {/* Budget Meters */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-white border border-slate-200 rounded-lg p-5">
          <div className="text-xs font-medium uppercase tracking-wider text-slate-500">
            Daily Token Budget ({modelConfig.model_name})
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-mono font-semibold text-slate-900 tabular-nums">
              {budgetToday.total_tokens.toLocaleString()}
            </span>
            <span className="text-xs font-mono text-slate-500 tabular-nums">
              / {budgetToday.daily_token_limit.toLocaleString()} tokens
            </span>
          </div>
          <div className="mt-3 h-2 w-full bg-slate-100 rounded-sm overflow-hidden">
            <div
              className="h-full bg-blue-600 transition-all"
              style={{ width: `${tokenPct}%` }}
            />
          </div>
          <div className="mt-2 text-xs font-mono text-slate-500 tabular-nums">
            Per-cycle ceiling: {budgetToday.cycle_token_limit.toLocaleString()} tokens
          </div>
        </div>

        <div className="bg-white border border-slate-200 rounded-lg p-5">
          <div className="text-xs font-medium uppercase tracking-wider text-slate-500">
            Daily Model Requests
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-mono font-semibold text-slate-900 tabular-nums">
              {budgetToday.requests_used}
            </span>
            <span className="text-xs font-mono text-slate-500 tabular-nums">
              / {budgetToday.daily_request_limit} requests
            </span>
          </div>
          <div className="mt-3 h-2 w-full bg-slate-100 rounded-sm overflow-hidden">
            <div
              className="h-full bg-cyan-600 transition-all"
              style={{ width: `${reqPct}%` }}
            />
          </div>
          <div className="mt-2 text-xs font-mono text-slate-500 tabular-nums">
            Provider key status:{" "}
            {modelConfig.gemini_configured ? "● Configured (server env)" : "○ Offline deterministic fallback"}
          </div>
        </div>

        <div className="bg-white border border-slate-200 rounded-lg p-5">
          <div className="text-xs font-medium uppercase tracking-wider text-slate-500">
            Deterministic Resolution Share
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-mono font-semibold text-slate-900 tabular-nums">
              {detRatio}%
            </span>
            <span className="text-xs font-mono text-slate-500 tabular-nums">
              ({budgetToday.deterministic_resolutions} zero-token)
            </span>
          </div>
          <p className="mt-3 text-xs text-slate-600">
            AST math, epistemic classification, memory recall, and safety screening run locally without LLM spend.
          </p>
        </div>
      </div>

      {/* Daily Usage Ledger */}
      <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-200">
          <h3 className="text-sm font-semibold text-slate-900">Daily Usage Ledger</h3>
        </div>
        {usageLedger.length === 0 ? (
          <div className="p-6 text-sm text-slate-500">
            No usage entries logged yet. Run a wake cycle to record deterministic or model activity.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-xs font-medium text-slate-500">
                  <th className="py-2.5 px-4">Date (UTC)</th>
                  <th className="py-2.5 px-4">Provider / Engine</th>
                  <th className="py-2.5 px-4 text-right">Requests</th>
                  <th className="py-2.5 px-4 text-right">Prompt Tokens</th>
                  <th className="py-2.5 px-4 text-right">Completion Tokens</th>
                  <th className="py-2.5 px-4 text-right">Deterministic</th>
                  <th className="py-2.5 px-4 text-right">Deferred</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-xs font-mono tabular-nums">
                {usageLedger.map((row, idx) => (
                  <tr key={`${row.usage_date}-${row.model_name}-${idx}`} className="hover:bg-slate-50">
                    <td className="py-2.5 px-4 text-slate-900">{row.usage_date}</td>
                    <td className="py-2.5 px-4 text-slate-700">
                      {row.provider} / {row.model_name}
                    </td>
                    <td className="py-2.5 px-4 text-right">{row.requests_used}</td>
                    <td className="py-2.5 px-4 text-right">{row.prompt_tokens}</td>
                    <td className="py-2.5 px-4 text-right">{row.completion_tokens}</td>
                    <td className="py-2.5 px-4 text-right text-emerald-700">
                      {row.deterministic_resolutions}
                    </td>
                    <td className="py-2.5 px-4 text-right text-amber-700">
                      {row.deferred_count}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Deferred Work Queue */}
      <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Deferred Work Queue</h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Tasks queued cleanly upon rate-limit or token-budget exhaustion to prevent request storms
            </p>
          </div>
          {deferredQueue.some((d) => d.status === "PENDING") && (
            <button
              type="button"
              disabled={busy}
              onClick={onResumeDeferred}
              className="px-3 py-1.5 text-xs font-medium bg-white border border-slate-300 text-slate-700 rounded-md hover:bg-slate-50 disabled:opacity-50 whitespace-nowrap shrink-0"
            >
              Retry Due Deferred Tasks
            </button>
          )}
        </div>
        {deferredQueue.length === 0 ? (
          <div className="p-6 text-sm text-slate-500">Deferred queue is clear.</div>
        ) : (
          <div className="divide-y divide-slate-100">
            {deferredQueue.map((item) => (
              <div key={item.queue_id} className="px-6 py-3 text-xs flex items-center justify-between gap-4">
                <div>
                  <div className="font-mono text-slate-900">
                    {item.operation_id} · retries={item.retry_count} · {item.status}
                  </div>
                  <div className="text-slate-600 mt-0.5">{item.reason}</div>
                </div>
                <div className="font-mono text-slate-500 tabular-nums shrink-0">
                  next retry {item.next_retry_at.slice(0, 19)}Z
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
