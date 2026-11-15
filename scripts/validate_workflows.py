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

    pub_script = root / "scripts" / "publish_encrypted_state.sh"
    if not pub_script.exists():
        raise AssertionError(f"Missing publish script: {pub_script}")
    pub_text = pub_script.read_text(encoding="utf-8")
    for req in ("git add -A", "state-verify-git-tree", "organism-state", "assert_no_plaintext_in_publish_dir"):
        if req not in pub_text:
            raise AssertionError(f"publish_encrypted_state.sh missing required safeguard: {req}")

    tg = (wf_dir / "telegram_polling.yml").read_text(encoding="utf-8")
    for req in (
        "schedule:",
        "workflow_dispatch:",
        "group: organism-state-persistence",
        "cancel-in-progress: false",
        "state-migrate-restore",
        "state-pack",
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
        "state-migrate-restore",
        "state-pack",
        "publish_encrypted_state.sh",
        "gemini-3.8-flash",
    ):
        if req not in wc:
            raise AssertionError(f"organism_cycle.yml missing required directive: {req}")

    ci = (wf_dir / "ci.yml").read_text(encoding="utf-8")
    for req in (
        "push:",
        'branches: ["main"]',
        'node-version: "22"',
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
