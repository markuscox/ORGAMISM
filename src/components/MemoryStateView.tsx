import { useState } from "react";
import type {
  ActiveExperiment,
  EpistemicType,
  EpisodicRecord,
  EvidenceRecord,
  KnowledgeGraphEdge,
  SemanticFact,
} from "../types";
import { StatusGlyph } from "./StatusGlyph";

interface Props {
  episodes: EpisodicRecord[];
  semanticFacts: SemanticFact[];
  evidenceRecords: EvidenceRecord[];
  kgEdges: KnowledgeGraphEdge[];
  activeExperiments: ActiveExperiment[];
  replayBufferCount: number;
  onExecuteExperiment: (expId: string) => void;
  onControlledForgetting: () => void;
  busy: boolean;
}

const EPISTEMIC_FILTERS: Array<"all" | EpistemicType> = [
  "all",
  "fact",
  "hypothesis",
  "prediction",
  "assumption",
  "unknown",
];

export function MemoryStateView({
  episodes,
  semanticFacts,
  evidenceRecords,
  kgEdges,
  activeExperiments,
  replayBufferCount,
  onExecuteExperiment,
  onControlledForgetting,
  busy,
}: Props) {
  const [epistemicFilter, setEpistemicFilter] = useState<"all" | EpistemicType>("all");
  const [showArchived, setShowArchived] = useState(true);

  const filteredFacts = semanticFacts.filter((f) => {
    if (epistemicFilter !== "all" && f.epistemic_type !== epistemicFilter) return false;
    if (!showArchived && (f.invalidated_at !== null || f.forgotten_at !== null)) return false;
    return true;
  });

  const factStatusTone = (fact: SemanticFact) => {
    if (fact.invalidated_at !== null) return "text-amber-700";
    if (fact.forgotten_at !== null || fact.status === "forgotten") return "text-slate-400";
    if (fact.status === "verified") return "text-emerald-700";
    if (fact.status === "evidence_checked") return "text-blue-700";
    if (fact.status === "rejected") return "text-rose-700";
    return "text-slate-600";
  };

  return (
    <div className="space-y-6">
      {/* Active Learning & Curiosity Probes */}
      <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-200 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-base font-semibold text-slate-900">
              Active Learning & Curiosity Probes
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Bounded internal verification experiments ranked by Expected Value of Information (EVI = EIG − cost) · Replay buffer: {replayBufferCount}
            </p>
          </div>
          <button
            type="button"
            disabled={busy}
            onClick={onControlledForgetting}
            className="px-3.5 py-2 text-xs font-medium bg-white border border-slate-300 text-slate-700 rounded-md hover:bg-slate-50 disabled:opacity-50 whitespace-nowrap shrink-0"
          >
            Run Controlled Forgetting
          </button>
        </div>

        {activeExperiments.length === 0 ? (
          <div className="p-6 text-xs text-slate-500">
            No curiosity probes proposed yet. Assert a candidate fact or hypothesis to trigger entropy-driven EVI scoring.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-xs font-medium text-slate-500">
                  <th className="py-2.5 px-4">Target / Hypothesis</th>
                  <th className="py-2.5 px-4 text-right">Entropy</th>
                  <th className="py-2.5 px-4 text-right">EIG</th>
                  <th className="py-2.5 px-4 text-right">EVI</th>
                  <th className="py-2.5 px-4">Status</th>
                  <th className="py-2.5 px-4 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-xs">
                {activeExperiments.slice(0, 10).map((exp) => (
                  <tr key={exp.experiment_id} className="hover:bg-slate-50">
                    <td className="py-2.5 px-4">
                      <div className="font-mono text-slate-900">{exp.hypothesis}</div>
                      <div className="text-slate-500 mt-0.5">
                        {exp.result_summary || exp.proposed_probe}
                      </div>
                    </td>
                    <td className="py-2.5 px-4 font-mono text-right tabular-nums text-slate-700">
                      {exp.uncertainty_entropy.toFixed(2)}
                    </td>
                    <td className="py-2.5 px-4 font-mono text-right tabular-nums text-slate-700">
                      {exp.expected_info_gain.toFixed(2)}
                    </td>
                    <td className="py-2.5 px-4 font-mono text-right tabular-nums font-semibold text-slate-900">
                      {exp.evi_score.toFixed(2)}
                    </td>
                    <td className="py-2.5 px-4 font-mono">
                      <span
                        className={
                          exp.status === "EXECUTED" ? "text-emerald-700" : "text-blue-700"
                        }
                      >
                        {exp.status === "EXECUTED" ? "● EXECUTED" : "▸ PROPOSED"}
                      </span>
                    </td>
                    <td className="py-2.5 px-4 text-right">
                      {exp.status === "PROPOSED" ? (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => onExecuteExperiment(exp.experiment_id)}
                          className="px-2.5 py-1 text-xs font-medium bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 whitespace-nowrap"
                        >
                          Execute Probe
                        </button>
                      ) : (
                        <span className="font-mono text-slate-400 tabular-nums">
                          gain {exp.info_gain_realized?.toFixed(2) ?? "0.00"}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Epistemic & Semantic Ledger */}
      <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-200 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-base font-semibold text-slate-900">
              Evidence-Based Epistemic &amp; Temporal Ledger
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Lifecycle: OBSERVED → CANDIDATE → EVIDENCE_CHECKED → VERIFIED | REJECTED · ACT-R activation decay &amp; selective forgetting
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1 p-1 bg-slate-100 rounded-lg">
              {EPISTEMIC_FILTERS.map((f) => (
                <button
                  key={f}
                  type="button"
                  onClick={() => setEpistemicFilter(f)}
                  className={`px-2.5 py-1 text-xs font-medium rounded-md transition-colors whitespace-nowrap shrink-0 ${
                    epistemicFilter === f
                      ? "bg-white text-slate-900 shadow-xs"
                      : "text-slate-600 hover:text-slate-900"
                  }`}
                >
                  {f}
                </button>
              ))}
            </div>
            <label className="flex items-center gap-2 text-xs text-slate-600 cursor-pointer select-none whitespace-nowrap">
              <input
                type="checkbox"
                checked={showArchived}
                onChange={(e) => setShowArchived(e.target.checked)}
                className="rounded border-slate-300 text-blue-600"
              />
              Show invalidated / forgotten
            </label>
          </div>
        </div>

        {filteredFacts.length === 0 ? (
          <div className="p-6 text-sm text-slate-500">
            No semantic records match the current filter. Try running a{" "}
            <span className="font-mono text-slate-700">fact: ...</span> or{" "}
            <span className="font-mono text-slate-700">hypothesis: ...</span> wake cycle.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-xs font-medium text-slate-500">
                  <th className="py-2.5 px-4">Assertion</th>
                  <th className="py-2.5 px-4">Epistemic</th>
                  <th className="py-2.5 px-4">Lifecycle Status</th>
                  <th className="py-2.5 px-4 text-right">Evidence</th>
                  <th className="py-2.5 px-4 text-right">Conf</th>
                  <th className="py-2.5 px-4 text-right">ACT-R</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-sm">
                {filteredFacts.map((fact) => {
                  const isArchived = fact.invalidated_at !== null || fact.forgotten_at !== null;
                  return (
                    <tr
                      key={fact.fact_id}
                      className={isArchived ? "bg-slate-50/70 text-slate-400" : "hover:bg-slate-50"}
                    >
                      <td className="py-2.5 px-4 font-mono text-xs">
                        <span className={fact.invalidated_at ? "line-through" : "text-slate-900"}>
                          {fact.subject} {fact.predicate} {fact.object_value}
                        </span>
                      </td>
                      <td className="py-2.5 px-4 font-mono text-xs text-slate-600">
                        {fact.epistemic_type}
                      </td>
                      <td className="py-2.5 px-4 font-mono text-xs">
                        <span className={factStatusTone(fact)}>
                          {fact.invalidated_at
                            ? "▲ invalidated"
                            : fact.forgotten_at
                            ? "· forgotten"
                            : `● ${fact.status}`}
                        </span>
                      </td>
                      <td className="py-2.5 px-4 font-mono text-xs text-right tabular-nums text-slate-600">
                        +{fact.evidence_count ?? 1} / -{fact.contradiction_count ?? 0}
                      </td>
                      <td className="py-2.5 px-4 font-mono text-xs text-right tabular-nums">
                        {(fact.confidence * 100).toFixed(0)}%
                      </td>
                      <td className="py-2.5 px-4 font-mono text-xs text-right tabular-nums text-slate-500">
                        {(fact.activation_score ?? fact.confidence).toFixed(2)} (x{fact.access_count ?? 1})
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Episodic Provenance History, Evidence Ledger & Temporal KG Edges */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
        <div className="xl:col-span-7 bg-white border border-slate-200 rounded-lg overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-200">
            <h3 className="text-sm font-semibold text-slate-900">
              Episodic Provenance Timeline
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Ordered causal sequence preserving original source, trust level, and outcome
            </p>
          </div>
          {episodes.length === 0 ? (
            <div className="p-6 text-sm text-slate-500">No episodes recorded yet.</div>
          ) : (
            <div className="divide-y divide-slate-100">
              {episodes.map((ep, idx) => (
                <div key={ep.episode_id} className="p-4 hover:bg-slate-50/60">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2 text-xs text-slate-500 font-mono tabular-nums">
                      <span>#{ep.sequence_index ?? episodes.length - idx}</span>
                      <span>{ep.episode_id}</span>
                      <span aria-hidden="true">·</span>
                      <span>{ep.source}</span>
                      <span aria-hidden="true">·</span>
                      <span>{ep.trust_level}</span>
                    </div>
                    <StatusGlyph status={ep.outcome_status} />
                  </div>
                  <p className="mt-1.5 text-sm font-medium text-slate-900">
                    {ep.event_content}
                  </p>
                  <p className="mt-1 text-xs text-slate-600">{ep.outcome_summary}</p>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="xl:col-span-5 space-y-6">
          <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-200">
              <h3 className="text-sm font-semibold text-slate-900">
                Evidence Corroboration Ledger
              </h3>
              <p className="text-xs text-slate-500 mt-0.5">
                Independent source weights &amp; duplicate-spam blocks
              </p>
            </div>
            {evidenceRecords.length === 0 ? (
              <div className="p-5 text-xs text-slate-500">No evidence entries yet.</div>
            ) : (
              <div className="divide-y divide-slate-100">
                {evidenceRecords.slice(0, 10).map((ev) => (
                  <div key={ev.evidence_id} className="px-5 py-2.5 text-xs">
                    <div className="flex items-center justify-between font-mono">
                      <span
                        className={
                          ev.stance === "support" ? "text-emerald-700" : "text-rose-700"
                        }
                      >
                        {ev.stance.toUpperCase()} · w={ev.weight.toFixed(2)}
                      </span>
                      <span className="text-slate-500">{ev.source}</span>
                    </div>
                    <div className="mt-1 text-slate-700">{ev.rationale}</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-200">
              <h3 className="text-sm font-semibold text-slate-900">
                Temporal Knowledge Graph Edges
              </h3>
              <p className="text-xs text-slate-500 mt-0.5">
                Graphiti-style relational links stored in SQLite
              </p>
            </div>
            {kgEdges.length === 0 ? (
              <div className="p-5 text-xs text-slate-500">No knowledge graph edges yet.</div>
            ) : (
              <div className="divide-y divide-slate-100">
                {kgEdges.slice(0, 12).map((edge) => (
                  <div key={edge.edge_id} className="px-5 py-3 text-xs">
                    <div className="font-mono text-slate-900">
                      {edge.source_entity}{" "}
                      <span className="text-blue-700">[{edge.relation}]</span>{" "}
                      {edge.target_entity}
                    </div>
                    <div className="mt-1 text-slate-500 font-mono tabular-nums">
                      {edge.episode_id} · conf {(edge.confidence * 100).toFixed(0)}%
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
