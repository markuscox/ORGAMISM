import type { CycleStatus } from "../types";

export function StatusGlyph({ status }: { status: CycleStatus | string }) {
  switch (status) {
    case "COMPLETED":
      return (
        <span className="font-mono text-xs font-medium text-emerald-700 whitespace-nowrap">
          ● COMPLETED
        </span>
      );
    case "WAITING":
      return (
        <span className="font-mono text-xs font-medium text-amber-700 whitespace-nowrap">
          ◐ WAITING
        </span>
      );
    case "DEFERRED":
      return (
        <span className="font-mono text-xs font-medium text-amber-700 whitespace-nowrap">
          ◷ DEFERRED
        </span>
      );
    case "FAILED_SAFE":
      return (
        <span className="font-mono text-xs font-medium text-rose-700 whitespace-nowrap">
          ✖ FAILED_SAFE
        </span>
      );
    case "RUNNING":
      return (
        <span className="font-mono text-xs font-medium text-blue-700 whitespace-nowrap">
          ▸ RUNNING
        </span>
      );
    default:
      return (
        <span className="font-mono text-xs font-medium text-slate-600 whitespace-nowrap">
          {status}
        </span>
      );
  }
}

export function StepStatusText({ status }: { status: string }) {
  const tone =
    status === "ok"
      ? "text-emerald-700"
      : status === "degraded"
      ? "text-amber-700"
      : status === "blocked" || status === "error"
      ? "text-rose-700"
      : "text-slate-500";
  const glyph =
    status === "ok"
      ? "●"
      : status === "degraded"
      ? "▲"
      : status === "blocked" || status === "error"
      ? "✖"
      : "·";

  return (
    <span className={`font-mono text-xs uppercase ${tone} whitespace-nowrap`}>
      {glyph} {status}
    </span>
  );
}
