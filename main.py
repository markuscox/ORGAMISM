"""CLI entrypoint for running discrete ORGANISM wake cycles, resumptions, approvals, experiments, and benchmarks."""

from __future__ import annotations

import argparse
import json
import sys
import uuid

from organism.config.settings import load_config
from organism.evaluation.benchmarks import run_all_benchmarks
from organism.kernel.contracts import CognitiveEvent, TrustLevel
from organism.kernel.runtime import CognitiveKernel


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ORGANISM Stage 2 Cognitive Kernel CLI")
    parser.add_argument("--state-dir", default=None, help="Override state directory path")
    sub = parser.add_subparsers(dest="command", required=True)

    wake = sub.add_parser("wake", help="Run a discrete wake cycle with an incoming event")
    wake.add_argument("--event", required=True, help="Incoming stimulus text")
    wake.add_argument("--source", default="cli_operator", help="Event source identifier")
    wake.add_argument(
        "--trust",
        default=TrustLevel.TRUSTED_OPERATOR.value,
        choices=[t.value for t in TrustLevel],
        help="Trust classification of event source",
    )
    wake.add_argument("--event-type", default="observation", help="Logical event type")
    wake.add_argument("--operation-id", default=None, help="Unique idempotency key")
    wake.add_argument(
        "--mode",
        default="auto",
        choices=["auto", "deterministic_only", "gemini_assisted"],
        help="Reasoning mode",
    )
    wake.add_argument("--approved", action="store_true", help="Explicit human approval flag")
    wake.add_argument("--crash-at-step", type=int, default=None, help="Simulate crash after step N")
    wake.add_argument("--fault-organ", default=None, help="Simulate isolated fault in named organ")

    resume = sub.add_parser("resume", help="Resume an interrupted RUNNING cycle")
    resume.add_argument("--cycle-id", default=None, help="Specific cycle_id to resume")
    resume.add_argument("--approved", action="store_true", help="Provide human approval on resume")
    resume.add_argument("--fault-organ", default=None, help="Optional fault organ simulation")

    approve = sub.add_parser("approve", help="Approve or reject a WAITING cycle")
    approve.add_argument("--cycle-id", required=True, help="Cycle ID in WAITING state")
    approve.add_argument("--decision", required=True, choices=["approve", "reject"])

    exp = sub.add_parser("experiment", help="Execute a safe bounded active-learning probe")
    exp.add_argument("--id", "--exp-id", dest="exp_id", required=True, help="Experiment ID to execute")

    sub.add_parser("consolidate", help="Run forgetting, Fisher EWC anchoring, replay rehearsal, and probe scan")
    sub.add_parser("replay", help="Run EWC-anchored continual learning replay rehearsal")
    sub.add_parser("forget", help="Run controlled selective forgetting on stale unverified clutter")
    sub.add_parser("status", help="Output full persisted organism state as JSON")
    sub.add_parser("eval", help="Run Stage 1 + Stage 2 automated capability benchmarks")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(state_dir_override=args.state_dir)
    kernel = CognitiveKernel(config=config)

    if args.command == "status":
        print(json.dumps(kernel.get_full_state(), indent=2, ensure_ascii=True))
        return 0

    if args.command == "eval":
        report = run_all_benchmarks(record_to_store=kernel)
        print(json.dumps(report, indent=2, ensure_ascii=True))
        return 0 if report["failed"] == 0 else 1

    if args.command == "experiment":
        res = kernel.run_active_experiment(args.exp_id)
        print(json.dumps({"experiment": res, "state": kernel.get_full_state()}, indent=2, ensure_ascii=True))
        return 0 if res is not None else 1

    if args.command == "consolidate":
        res = kernel.run_maintenance_consolidation()
        print(json.dumps({"consolidation": res, "state": kernel.get_full_state()}, indent=2, ensure_ascii=True))
        return 0

    if args.command == "replay":
        res = kernel.continual.replay_rehearsal()
        kernel.store.export_snapshot()
        print(json.dumps({"replay": res, "state": kernel.get_full_state()}, indent=2, ensure_ascii=True))
        return 0

    if args.command == "forget":
        res = kernel.retriever.apply_controlled_forgetting()
        kernel.store.export_snapshot()
        print(json.dumps({"forgetting": res, "state": kernel.get_full_state()}, indent=2, ensure_ascii=True))
        return 0

    if args.command == "wake":
        op_id = args.operation_id or f"op_{uuid.uuid4().hex[:12]}"
        ev = CognitiveEvent(
            event_id=f"ev_{uuid.uuid4().hex[:10]}",
            operation_id=op_id,
            source=args.source,
            trust_level=TrustLevel(args.trust),
            event_type=args.event_type,
            content=args.event,
        )
        cp = kernel.run_cycle(
            event=ev,
            mode=args.mode,
            approved_by_human=bool(args.approved),
            simulate_crash_at_step=args.crash_at_step,
            simulate_fault_organ=args.fault_organ,
        )
        print(json.dumps({"cycle": cp.to_dict(), "state": kernel.get_full_state()}, indent=2, ensure_ascii=True))
        return 0

    if args.command == "resume":
        cp = kernel.resume_cycle(
            cycle_id=args.cycle_id,
            approved_by_human=bool(args.approved),
            simulate_fault_organ=args.fault_organ,
        )
        if cp is None:
            deferred_ev = kernel.scheduler.find_due_deferred_event()
            if deferred_ev is not None:
                cp = kernel.run_cycle(deferred_ev)
        print(
            json.dumps(
                {
                    "resumed": cp is not None,
                    "cycle": cp.to_dict() if cp else None,
                    "state": kernel.get_full_state(),
                },
                indent=2,
                ensure_ascii=True,
            )
        )
        return 0

    if args.command == "approve":
        cp = kernel.approve_cycle(args.cycle_id, approve=(args.decision == "approve"))
        print(
            json.dumps(
                {
                    "updated": cp is not None,
                    "cycle": cp.to_dict() if cp else None,
                    "state": kernel.get_full_state(),
                },
                indent=2,
                ensure_ascii=True,
            )
        )
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
