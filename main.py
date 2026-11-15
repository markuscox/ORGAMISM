"""CLI entrypoint for running discrete ORGANISM wake cycles, resumptions, approvals, encrypted state, Telegram polling, and benchmarks."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from organism.config.settings import load_config
from organism.evaluation.benchmarks import run_all_benchmarks
from organism.integrations.telegram import TelegramBridge
from organism.kernel.contracts import CognitiveEvent, TrustLevel
from organism.kernel.runtime import CognitiveKernel
from organism.models.gemini import GeminiProvider
from organism.models.provider import ProviderError
from organism.safety.state_crypto import (
    StateCryptoError,
    StateEncryptor,
    assert_clean_git_publish_tree,
    assert_no_plaintext_in_publish_dir,
    generate_fernet_key,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ORGANISM Stage 3 Cognitive Kernel CLI")
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
    wake.add_argument("--session-id", default="default", help="Logical dialogue session identifier")

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

    # Stage 3 state encryption & Telegram polling commands
    sub.add_parser("keygen", help="Generate a fresh Fernet key for ORGANISM_STATE_ENCRYPTION_KEY")

    pack = sub.add_parser("state-pack", help="Safely backup SQLite WAL + encrypt state bundle")
    pack.add_argument("--encrypted-dir", default="encrypted_state", help="Output directory for encrypted bundle")
    pack.add_argument("--verify-no-plaintext", action="store_true", help="Verify zero plaintext artifacts exist")

    unpack = sub.add_parser("state-unpack", help="Decrypt and integrity-check encrypted state bundle")
    unpack.add_argument("--encrypted-dir", default="encrypted_state", help="Input directory containing encrypted bundle")
    unpack.add_argument("--allow-empty", action="store_true", help="Allow initialization if bundle does not exist yet")

    migrate = sub.add_parser(
        "state-migrate-restore",
        help="Restore encrypted bundle or safely migrate verified legacy state/ into encrypted bundle",
    )
    migrate.add_argument("--encrypted-dir", default="encrypted_state", help="Directory containing encrypted bundle")
    migrate.add_argument("--legacy-state-dir", default=None, help="Legacy plaintext state directory to migrate if no bundle exists")
    migrate.add_argument("--allow-empty", action="store_true", help="Allow initialization if neither bundle nor legacy DB exists")

    verify_git = sub.add_parser(
        "state-verify-git-tree",
        help="Assert checked-out state repository contains ONLY encrypted artifacts in tip and history",
    )
    verify_git.add_argument("--repo-dir", required=True, help="Checked-out organism-state repository directory")
    verify_git.add_argument("--check-history", action="store_true", help="Also verify full commit history contains zero plaintext")

    verify_bundle = sub.add_parser(
        "state-verify-bundle",
        help="Decrypt Fernet bundle into temp dir, check SQLite/snapshot integrity, and compare tables with state-dir",
    )
    verify_bundle.add_argument("--encrypted-dir", default="encrypted_state", help="Directory containing encrypted bundle")
    verify_bundle.add_argument(
        "--expected-state-dir",
        default=None,
        help="Optional local state_dir to compare against decrypted bundle contents",
    )

    sub.add_parser("gemini-probe", help="Verify live Gemini API connectivity, response, and usageMetadata safely")

    tg = sub.add_parser("telegram-poll", help="Poll Telegram Bot API once and process verified owner updates")
    tg.add_argument("--limit", type=int, default=25, help="Maximum updates to fetch")
    tg.add_argument("--timeout", type=int, default=5, help="Telegram long-poll timeout in seconds")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(state_dir_override=args.state_dir)

    if args.command == "keygen":
        print(generate_fernet_key())
        return 0

    if args.command == "state-verify-git-tree":
        try:
            res = assert_clean_git_publish_tree(
                Path(args.repo_dir),
                check_history=bool(args.check_history),
            )
            print(json.dumps(res, indent=2, ensure_ascii=True))
            return 0
        except StateCryptoError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2

    if args.command == "state-verify-bundle":
        try:
            encryptor = StateEncryptor()
            expected_dir = Path(args.expected_state_dir) if args.expected_state_dir else None
            res = encryptor.verify_bundle_matches_state(
                encrypted_dir=Path(args.encrypted_dir),
                expected_state_dir=expected_dir,
            )
            print(json.dumps(res, indent=2, ensure_ascii=True))
            return 0
        except StateCryptoError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2

    if args.command == "gemini-probe":
        provider = GeminiProvider(
            model_name=config.model_name,
            timeout_seconds=config.timeout_seconds,
            max_retries=config.max_retries,
            backoff_base_seconds=config.backoff_base_seconds,
        )
        try:
            res = provider.probe()
            print(json.dumps(res, indent=2, ensure_ascii=True))
            return 0
        except ProviderError as exc:
            print(json.dumps({"ok": False, "model_name": config.model_name, "error": str(exc)}), file=sys.stderr)
            return 2

    if args.command == "state-migrate-restore":
        try:
            encryptor = StateEncryptor()
            res = encryptor.migrate_or_restore(
                state_dir=config.state_dir,
                encrypted_dir=Path(args.encrypted_dir),
                legacy_state_dir=Path(args.legacy_state_dir) if args.legacy_state_dir else None,
                allow_empty=bool(args.allow_empty),
            )
            print(json.dumps(res, indent=2, ensure_ascii=True))
            return 0
        except StateCryptoError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2

    if args.command == "state-unpack":
        try:
            encryptor = StateEncryptor()
        except StateCryptoError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2

        enc_dir = Path(args.encrypted_dir)
        bundle = enc_dir / StateEncryptor.BUNDLE_FILENAME
        if not bundle.exists():
            if args.allow_empty:
                config.state_dir.mkdir(parents=True, exist_ok=True)
                print(json.dumps({"unpacked": False, "initialized_empty": True}, indent=2))
                return 0
            print(json.dumps({"error": f"Encrypted bundle missing at {bundle}"}), file=sys.stderr)
            return 2
        try:
            result = encryptor.unpack_state_dir(enc_dir, config.state_dir)
            print(json.dumps({"unpacked": True, **result}, indent=2, ensure_ascii=True))
            return 0
        except StateCryptoError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2

    if args.command == "state-pack":
        try:
            # Ensure DB/snapshot exists cleanly before packing
            kernel = CognitiveKernel(config=config)
            kernel.store.export_snapshot()
            encryptor = StateEncryptor()
            meta = encryptor.pack_state_dir(config.state_dir, Path(args.encrypted_dir))
            if args.verify_no_plaintext:
                assert_no_plaintext_in_publish_dir(Path(args.encrypted_dir))
            print(json.dumps({"packed": True, **meta}, indent=2, ensure_ascii=True))
            return 0
        except StateCryptoError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2

    kernel = CognitiveKernel(config=config)

    if args.command == "status":
        print(json.dumps(kernel.get_full_state(), indent=2, ensure_ascii=True))
        return 0

    if args.command == "eval":
        report = run_all_benchmarks(record_to_store=kernel)
        print(json.dumps(report, indent=2, ensure_ascii=True))
        return 0 if report["failed"] == 0 else 1

    if args.command == "telegram-poll":
        bridge = TelegramBridge(kernel=kernel)
        res = bridge.poll_once(limit=args.limit, timeout=args.timeout)
        print(json.dumps(res, indent=2, ensure_ascii=True))
        return 0

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
            metadata={"session_id": args.session_id},
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
