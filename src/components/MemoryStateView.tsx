import { useState } from "react";
import type {
  EpistemicType,
  EpisodicRecord,
  KnowledgeGraphEdge,
  SemanticFact,
} from "../types";
import { StatusGlyph } from "./StatusGlyph";

interface Props {
  episodes: EpisodicRecord[];
  semanticFacts: SemanticFact[];
  kgEdges: KnowledgeGraphEdge[];
}

const EPISTEMIC_FILTERS: Array<"all" | EpistemicType> = [
  "all",
  "fact",
  "hypothesis",
  "prediction",
  "assumption",
  "unknown",
];

export function MemoryStateView({ episodes, semanticFacts, kgEdges }: Props) {
  const [epistemicFilter, setEpistemicFilter] = useState<"all" | EpistemicType>("all");
  const [showInvalidated, setShowInvalidated] = useState(true);

  const filteredFacts = semanticFacts.filter((f) => {
    if (epistemicFilter !== "all" && f.epistemic_type !== epistemicFilter) return false;
    if (!showInvalidated && f.invalidated_at !== null) return false;
    return true;
  });

  return (
    <div className="space-y-6">
      {/* Epistemic & Semantic Ledger */}
      <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-200 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-base font-semibold text-slate-900">
              Epistemic & Temporal Knowledge Ledger
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Provenance-linked assertions separating verified facts from hypotheses and invalidated contradictions
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
                checked={showInvalidated}
                onChange={(e) => setShowInvalidated(e.target.checked)}
                className="rounded border-slate-300 text-blue-600"
              />
              Show invalidated history
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
                  <th className="py-2.5 px-4">Epistemic Type</th>
                  <th className="py-2.5 px-4">Status</th>
                  <th className="py-2.5 px-4 text-right">Confidence</th>
                  <th className="py-2.5 px-4">Provenance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-sm">
                {filteredFacts.map((fact) => {
                  const isInvalidated = fact.invalidated_at !== null;
                  return (
                    <tr
                      key={fact.fact_id}
                      className={isInvalidated ? "bg-slate-50/70 text-slate-400" : "hover:bg-slate-50"}
                    >
                      <td className="py-2.5 px-4 font-mono text-xs">
                        <span className={isInvalidated ? "line-through" : "text-slate-900"}>
                          {fact.subject} {fact.predicate} {fact.object_value}
                        </span>
                      </td>
                      <td className="py-2.5 px-4 font-mono text-xs text-slate-600">
                        {fact.epistemic_type}
                      </td>
                      <td className="py-2.5 px-4 font-mono text-xs">
                        {isInvalidated ? (
                          <span className="text-amber-700">▲ invalidated</span>
                        ) : (
                          <span className="text-emerald-700">● {fact.status}</span>
                        )}
                      </td>
                      <td className="py-2.5 px-4 font-mono text-xs text-right tabular-nums">
                        {(fact.confidence * 100).toFixed(0)}%
                      </td>
                      <td className="py-2.5 px-4 font-mono text-xs text-slate-500">
                        {fact.source_episode_id}
                        {fact.superseded_by ? ` → ${fact.superseded_by}` : ""}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Episodic Provenance History & Temporal KG Edges */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
        <div className="xl:col-span-7 bg-white border border-slate-200 rounded-lg overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-200">
            <h3 className="text-sm font-semibold text-slate-900">
              Episodic Provenance Timeline
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Append-only ordered experiences preserving original source, trust level, and outcome
            </p>
          </div>
          {episodes.length === 0 ? (
            <div className="p-6 text-sm text-slate-500">No episodes recorded yet.</div>
          ) : (
            <div className="divide-y divide-slate-100">
              {episodes.map((ep) => (
                <div key={ep.episode_id} className="p-4 hover:bg-slate-50/60">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2 text-xs text-slate-500 font-mono tabular-nums">
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

        <div className="xl:col-span-5 bg-white border border-slate-200 rounded-lg overflow-hidden">
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
              {kgEdges.slice(0, 15).map((edge) => (
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
  );
}
