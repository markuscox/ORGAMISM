"""Strict structural & security validator for GitHub Actions workflows (stdlib-only)."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any


def validate_workflows(repo_root: Path | None = None) -> dict[str, Any]:
    root = Path(repo_root or Path(__file__).resolve().parent.parent)
    wf_dir = root / ".github" / "workflows"
    if not wf_dir.exists():
        raise AssertionError(f"Workflow directory missing: {wf_dir}")

    files = sorted(wf_dir.glob("*.yml"))
    if not files:
        raise AssertionError("No .yml workflows found")

    results: dict[str, Any] = {}
    for path in files:
        raw = path.read_text(encoding="utf-8")
        lines = raw.splitlines()
        for idx, line in enumerate(lines, start=1):
            if "\t" in line:
                raise AssertionError(f"{path.name}:{idx} contains hard tab character (invalid YAML indentation)")

        for key in ("name:", "on:", "jobs:"):
            if not any(line.startswith(key) for line in lines):
                raise AssertionError(f"{path.name} missing required top-level key '{key}'")

        # Ensure forbidden contexts (`${{ runner.* }}`, `${{ secrets.* }}`) never appear in job-level env:
        in_job_env = False
        job_env_indent = 0
        for idx, line in enumerate(lines, start=1):
            stripped = line.lstrip(" ")
            indent = len(line) - len(stripped)
            if re.match(r"^\s{4}env:\s*$", line):
                in_job_env = True
                job_env_indent = indent
                continue
            if in_job_env:
                if stripped and indent <= job_env_indent:
                    in_job_env = False
                elif "${{ runner." in line or "${{ secrets." in line:
                    raise AssertionError(
                        f"{path.name}:{idx} uses forbidden expression in job-level env: {stripped}"
                    )

        # Ensure zero unescaped ${{ github.event.inputs.* }} or ${{ secrets.* }} inside `run:` shell scripts
        in_run_block = False
        run_indent = 0
        for idx, line in enumerate(lines, start=1):
            stripped = line.lstrip(" ")
            indent = len(line) - len(stripped)
            if re.match(r"^\s*run:\s*\|?\s*", line):
                in_run_block = True
                run_indent = indent
                if "${{ github.event.inputs." in line or "${{ secrets." in line:
                    raise AssertionError(f"{path.name}:{idx} interpolates untrusted/secret context directly in run:")
                continue
            if in_run_block:
                if stripped and indent <= run_indent:
                    in_run_block = False
                elif "${{ github.event.inputs." in line:
                    raise AssertionError(
                        f"{path.name}:{idx} directly interpolates github.event.inputs inside shell run block"
                    )
                elif "${{ secrets." in line:
                    raise AssertionError(
                        f"{path.name}:{idx} directly interpolates secrets inside shell run block"
                    )

        results[path.name] = {"lines": len(lines), "valid": True}

    scripts_dir = root / "scripts"
    pub_script = scripts_dir / "publish_encrypted_state.sh"
    fetch_script = scripts_dir / "fetch_state_branch.sh"
    sync_py = scripts_dir / "git_state_sync.py"
    for p in (pub_script, fetch_script, sync_py):
        if not p.exists():
            raise AssertionError(f"Missing Git sync script: {p}")

    pub_text = pub_script.read_text(encoding="utf-8")
    for req in ("git_state_sync.py", "publish", "organism-state", "--expected-state-dir"):
        if req not in pub_text:
            raise AssertionError(f"publish_encrypted_state.sh missing required directive: {req}")

    fetch_text = fetch_script.read_text(encoding="utf-8")
    for req in ("git_state_sync.py", "fetch", "organism-state"):
        if req not in fetch_text:
            raise AssertionError(f"fetch_state_branch.sh missing required directive: {req}")

    sync_text = sync_py.read_text(encoding="utf-8")
    for req in (
        "GIT_CONFIG_COUNT",
        "extraheader",
        "ls-remote",
        "assert_clean_git_publish_tree",
        "assert_no_plaintext_in_publish_dir",
        "verify_bundle_matches_state",
    ):
        if req not in sync_text:
            raise AssertionError(f"git_state_sync.py missing required safeguard: {req}")

    tg = (wf_dir / "telegram_polling.yml").read_text(encoding="utf-8")
    for req in (
        "schedule:",
        "workflow_dispatch:",
        "group: organism-state-persistence",
        "cancel-in-progress: false",
        "$RUNNER_TEMP",
        "$GITHUB_ENV",
        "GH_TOKEN: ${{ github.token }}",
        "fetch_state_branch.sh",
        "STATE_BRANCH_EXISTS",
        "state-migrate-restore",
        "state-pack",
        "state-verify-bundle",
        "publish_encrypted_state.sh",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_OWNER_ID",
        "ORGANISM_STATE_ENCRYPTION_KEY",
        "GEMINI_API_KEY",
        "gemini-3.8-flash",
    ):
        if req not in tg:
            raise AssertionError(f"telegram_polling.yml missing required directive: {req}")
    if "ORGANISM_ADMIN_TOKEN" in tg:
        raise AssertionError("telegram_polling.yml must not receive ORGANISM_ADMIN_TOKEN")

    wc = (wf_dir / "organism_cycle.yml").read_text(encoding="utf-8")
    for req in (
        "schedule:",
        "workflow_dispatch:",
        "group: organism-state-persistence",
        "cancel-in-progress: false",
        "$RUNNER_TEMP",
        "$GITHUB_ENV",
        "GH_TOKEN: ${{ github.token }}",
        "fetch_state_branch.sh",
        "STATE_BRANCH_EXISTS",
        "state-migrate-restore",
        "state-pack",
        "state-verify-bundle",
        "publish_encrypted_state.sh",
        "gemini-3.8-flash",
    ):
        if req not in wc:
            raise AssertionError(f"organism_cycle.yml missing required directive: {req}")

    ci = (wf_dir / "ci.yml").read_text(encoding="utf-8")
    for req in (
        "push:",
        'branches: ["main"]',
        "workflow-lint:",
        "python-tests:",
        "node-build:",
        "gemini-probe:",
        'python-version: "3.11"',
        'node-version: "22"',
        "actionlint",
        "npm ci",
        "npm run lint",
        "npm run build",
        "unittest discover",
        "validate_workflows.py",
    ):
        if req not in ci:
            raise AssertionError(f"ci.yml missing required directive: {req}")

    return {"workflows": results, "status": "ok"}


if __name__ == "__main__":
    summary = validate_workflows()
    print(f"Workflow validation passed: {', '.join(sorted(summary['workflows'].keys()))}")
    sys.exit(0)
