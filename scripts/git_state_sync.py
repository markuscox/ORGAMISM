"""Secure isolated Git synchronization for the `organism-state` branch (no token leakage in URLs/config/logs)."""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any, Mapping

from organism.safety.state_crypto import (
    StateCryptoError,
    StateEncryptor,
    assert_clean_git_publish_tree,
    assert_no_plaintext_in_publish_dir,
)


class GitSyncError(RuntimeError):
    """Raised on Git authentication, network, fetch, push, or verification failure."""


def _redact_secret(text: str, token: str | None) -> str:
    cleaned = text or ""
    tok = (token or "").strip()
    if tok:
        cleaned = cleaned.replace(tok, "[REDACTED_GH_TOKEN]")
        basic_raw = base64.b64encode(f"x-access-token:{tok}".encode("utf-8")).decode("ascii")
        cleaned = cleaned.replace(basic_raw, "[REDACTED_GH_AUTH]")
    return cleaned


def _validate_clean_remote_url(remote_url: str, token: str | None = None) -> str:
    url = remote_url.strip()
    if not url:
        raise GitSyncError("REMOTE_URL is empty.")
    tok = (token or "").strip()
    if tok and tok in url:
        raise GitSyncError("Refusing REMOTE_URL containing an embedded credential token.")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() in ("http", "https") and (parsed.username or parsed.password):
        raise GitSyncError("Refusing HTTP(S) REMOTE_URL containing embedded username/password.")
    return url


def build_git_auth_env(
    remote_url: str,
    token: str | None = None,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """
    Build a transient subprocess environment injecting Git HTTP basic extraheader
    when `remote_url` is HTTP(S) and `token` is provided.
    Never writes credentials into `.git/config`, remote URLs, or logs.
    """
    env = dict(base_env if base_env is not None else os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    tok = (token or "").strip()
    if not tok:
        return env

    parsed = urllib.parse.urlsplit(remote_url.strip())
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return env

    scope_url = f"{parsed.scheme.lower()}://{parsed.netloc}/"
    basic_b64 = base64.b64encode(f"x-access-token:{tok}".encode("utf-8")).decode("ascii")

    try:
        existing_count = int(env.get("GIT_CONFIG_COUNT", "0"))
    except ValueError:
        existing_count = 0

    env["GIT_CONFIG_COUNT"] = str(existing_count + 1)
    env[f"GIT_CONFIG_KEY_{existing_count}"] = f"http.{scope_url}.extraheader"
    env[f"GIT_CONFIG_VALUE_{existing_count}"] = f"Authorization: Basic {basic_b64}"
    return env


def _run_git(
    args: list[str],
    cwd: Path,
    remote_url: str,
    token: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = build_git_auth_env(remote_url=remote_url, token=token)
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        err = _redact_secret((proc.stderr or proc.stdout).strip(), token)
        raise GitSyncError(f"git {' '.join(args)} failed (exit {proc.returncode}): {err}")
    return proc


def _classify_ls_remote_failure(returncode: int, stderr: str, token: str | None) -> str:
    safe_err = _redact_secret(stderr.strip(), token)
    lower = safe_err.lower()
    if any(
        marker in lower
        for marker in (
            "authentication failed",
            "could not read username",
            "401",
            "403",
            "forbidden",
            "invalid username or token",
            "bad credentials",
            "permission to",
            "denied to",
        )
    ):
        return f"Git authentication/authorization error while checking remote branch (exit {returncode}): {safe_err}"
    if any(
        marker in lower
        for marker in (
            "could not resolve host",
            "failed to connect",
            "timed out",
            "connection refused",
            "network is unreachable",
            "ssl",
            "unable to access",
            "the requested url returned error: 5",
        )
    ):
        return f"Git network/transport error while checking remote branch (exit {returncode}): {safe_err}"
    return f"Git ls-remote failed unexpectedly (exit {returncode}): {safe_err}"


def probe_remote_branch(
    repo_dir: Path,
    remote_url: str,
    branch: str = "organism-state",
    token: str | None = None,
) -> dict[str, Any]:
    """
    Strictly probe whether `branch` exists on `remote_url`:
      - rc == 0 -> branch exists
      - rc == 2 -> remote reachable & authorized, branch genuinely absent
      - rc != 0, 2 -> fatal auth / network error (fail closed)
    """
    clean_url = _validate_clean_remote_url(remote_url, token=token)
    proc = _run_git(
        ["ls-remote", "--exit-code", "--heads", clean_url, branch],
        cwd=repo_dir,
        remote_url=clean_url,
        token=token,
        check=False,
    )
    if proc.returncode == 0:
        oid = ""
        for line in proc.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2 and parts[1] == f"refs/heads/{branch}":
                oid = parts[0]
                break
        return {"exists": True, "remote_oid": oid}
    if proc.returncode == 2:
        return {"exists": False, "remote_oid": None}
    raise GitSyncError(_classify_ls_remote_failure(proc.returncode, proc.stderr or proc.stdout, token))


def _ensure_isolated_repo(state_repo_dir: Path, remote_url: str, token: str | None = None) -> str:
    clean_url = _validate_clean_remote_url(remote_url, token=token)
    state_repo_dir.mkdir(parents=True, exist_ok=True)
    if not (state_repo_dir / ".git").exists():
        _run_git(["init", "-q"], cwd=state_repo_dir, remote_url=clean_url, token=token)
    existing = _run_git(["remote"], cwd=state_repo_dir, remote_url=clean_url, token=token).stdout.splitlines()
    if "origin" in existing:
        current_url = _run_git(
            ["remote", "get-url", "origin"], cwd=state_repo_dir, remote_url=clean_url, token=token
        ).stdout.strip()
        if current_url != clean_url:
            _run_git(
                ["remote", "set-url", "origin", clean_url],
                cwd=state_repo_dir,
                remote_url=clean_url,
                token=token,
            )
    else:
        _run_git(
            ["remote", "add", "origin", clean_url],
            cwd=state_repo_dir,
            remote_url=clean_url,
            token=token,
        )
    return clean_url


def fetch_state_branch(
    state_repo_dir: Path,
    remote_url: str,
    encrypted_dir: Path,
    legacy_state_dir: Path,
    branch: str = "organism-state",
    token: str | None = None,
) -> dict[str, Any]:
    """Fetch `branch` into isolated `state_repo_dir`, failing closed on auth/network/fetch errors."""
    state_repo_dir = Path(state_repo_dir)
    encrypted_dir = Path(encrypted_dir)
    legacy_state_dir = Path(legacy_state_dir)
    encrypted_dir.mkdir(parents=True, exist_ok=True)
    legacy_state_dir.mkdir(parents=True, exist_ok=True)

    clean_url = _ensure_isolated_repo(state_repo_dir, remote_url, token=token)
    probe = probe_remote_branch(state_repo_dir, clean_url, branch=branch, token=token)
    if not probe["exists"]:
        return {
            "branch_exists": False,
            "fetched": False,
            "remote_oid": None,
            "has_encrypted": False,
            "has_legacy": False,
        }

    # Branch exists: fetch MUST succeed (never treat fetch failure as empty state)
    _run_git(
        ["fetch", "--no-tags", clean_url, f"+refs/heads/{branch}:refs/remotes/origin/{branch}"],
        cwd=state_repo_dir,
        remote_url=clean_url,
        token=token,
    )
    remote_oid = _run_git(
        ["rev-parse", f"refs/remotes/origin/{branch}"],
        cwd=state_repo_dir,
        remote_url=clean_url,
        token=token,
    ).stdout.strip()
    _run_git(
        ["checkout", "-B", branch, remote_oid],
        cwd=state_repo_dir,
        remote_url=clean_url,
        token=token,
    )

    has_encrypted = False
    enc_src = state_repo_dir / "encrypted_state"
    if enc_src.is_dir():
        for item in enc_src.iterdir():
            if item.is_file():
                shutil.copy2(item, encrypted_dir / item.name)
                has_encrypted = True

    has_legacy = False
    leg_src = state_repo_dir / "state"
    if leg_src.is_dir():
        for item in leg_src.iterdir():
            if item.is_file():
                shutil.copy2(item, legacy_state_dir / item.name)
                has_legacy = True

    return {
        "branch_exists": True,
        "fetched": True,
        "remote_oid": remote_oid,
        "has_encrypted": has_encrypted,
        "has_legacy": has_legacy,
    }


def _copy_dir_contents(src_dir: Path, dst_dir: Path) -> None:
    dst_dir.mkdir(parents=True, exist_ok=True)
    for item in src_dir.iterdir():
        if item.is_file():
            shutil.copy2(item, dst_dir / item.name)
        elif item.is_dir():
            shutil.copytree(item, dst_dir / item.name, dirs_exist_ok=True)


def publish_state_branch(
    state_repo_dir: Path,
    remote_url: str,
    encrypted_dir: Path,
    expected_state_dir: Path | None = None,
    branch: str = "organism-state",
    commit_message: str = "chore(state): persist encrypted cognitive state",
    purge_plaintext_history: bool = False,
    token: str | None = None,
    author_name: str = "organism-runner[bot]",
    author_email: str = "organism-runner[bot]@users.noreply.github.com",
    encryption_key: str | None = None,
) -> dict[str, Any]:
    """
    Verify Fernet bundle integrity & content equivalence BEFORE rewriting Git history,
    cleanly orphan-rewrite `organism-state` when needed (never modifying `main`),
    audit tip + full history, push with transient extraheader auth, and re-verify via fresh clone.
    """
    state_repo_dir = Path(state_repo_dir)
    encrypted_dir = Path(encrypted_dir)
    bundle_path = encrypted_dir / StateEncryptor.BUNDLE_FILENAME
    if not bundle_path.exists():
        raise GitSyncError(f"Refusing to publish: encrypted bundle missing at {bundle_path}")

    assert_no_plaintext_in_publish_dir(encrypted_dir)

    resolved_key = encryption_key if encryption_key is not None else os.environ.get("ORGANISM_STATE_ENCRYPTION_KEY", "")
    if resolved_key.strip():
        encryptor = StateEncryptor(key=resolved_key)
        encryptor.verify_bundle_matches_state(
            encrypted_dir=encrypted_dir,
            expected_state_dir=expected_state_dir,
        )

    clean_url = _ensure_isolated_repo(state_repo_dir, remote_url, token=token)
    _run_git(["config", "user.name", author_name], cwd=state_repo_dir, remote_url=clean_url, token=token)
    _run_git(["config", "user.email", author_email], cwd=state_repo_dir, remote_url=clean_url, token=token)

    probe = probe_remote_branch(state_repo_dir, clean_url, branch=branch, token=token)
    has_remote_branch = bool(probe["exists"])
    old_remote_oid = ""

    if has_remote_branch:
        _run_git(
            ["fetch", "--no-tags", clean_url, f"+refs/heads/{branch}:refs/remotes/origin/{branch}"],
            cwd=state_repo_dir,
            remote_url=clean_url,
            token=token,
        )
        old_remote_oid = _run_git(
            ["rev-parse", f"refs/remotes/origin/{branch}"],
            cwd=state_repo_dir,
            remote_url=clean_url,
            token=token,
        ).stdout.strip()
        _run_git(
            ["checkout", "-B", branch, old_remote_oid],
            cwd=state_repo_dir,
            remote_url=clean_url,
            token=token,
        )

    needs_orphan_rewrite = (not has_remote_branch) or bool(purge_plaintext_history)
    if not needs_orphan_rewrite:
        try:
            assert_clean_git_publish_tree(state_repo_dir, check_history=True)
        except StateCryptoError:
            needs_orphan_rewrite = True

    if needs_orphan_rewrite:
        orphan_tmp_branch = f"{branch}-clean"
        _run_git(["checkout", "--orphan", orphan_tmp_branch], cwd=state_repo_dir, remote_url=clean_url, token=token)
        _run_git(
            ["rm", "-rf", "--ignore-unmatch", "."],
            cwd=state_repo_dir,
            remote_url=clean_url,
            token=token,
            check=False,
        )
        for item in list(state_repo_dir.iterdir()):
            if item.name == ".git":
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        _copy_dir_contents(encrypted_dir, state_repo_dir / "encrypted_state")
        _run_git(["add", "-A"], cwd=state_repo_dir, remote_url=clean_url, token=token)
        assert_clean_git_publish_tree(state_repo_dir, check_history=False)
        _run_git(["commit", "-m", commit_message], cwd=state_repo_dir, remote_url=clean_url, token=token)
        _run_git(["branch", "-M", orphan_tmp_branch, branch], cwd=state_repo_dir, remote_url=clean_url, token=token)
        assert_clean_git_publish_tree(state_repo_dir, check_history=True)
        if has_remote_branch:
            _run_git(
                [
                    "push",
                    f"--force-with-lease=refs/heads/{branch}:{old_remote_oid}",
                    clean_url,
                    f"HEAD:refs/heads/{branch}",
                ],
                cwd=state_repo_dir,
                remote_url=clean_url,
                token=token,
            )
        else:
            _run_git(
                ["push", clean_url, f"HEAD:refs/heads/{branch}"],
                cwd=state_repo_dir,
                remote_url=clean_url,
                token=token,
            )
    else:
        for item in list(state_repo_dir.iterdir()):
            if item.name in (".git", "encrypted_state"):
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        enc_target = state_repo_dir / "encrypted_state"
        if enc_target.exists():
            shutil.rmtree(enc_target)
        _copy_dir_contents(encrypted_dir, enc_target)
        _run_git(["add", "-A"], cwd=state_repo_dir, remote_url=clean_url, token=token)
        assert_clean_git_publish_tree(state_repo_dir, check_history=False)
        diff_proc = _run_git(
            ["diff", "--cached", "--quiet"],
            cwd=state_repo_dir,
            remote_url=clean_url,
            token=token,
            check=False,
        )
        if diff_proc.returncode != 0:
            _run_git(["commit", "-m", commit_message], cwd=state_repo_dir, remote_url=clean_url, token=token)
            assert_clean_git_publish_tree(state_repo_dir, check_history=True)
            _run_git(
                ["push", clean_url, f"HEAD:refs/heads/{branch}"],
                cwd=state_repo_dir,
                remote_url=clean_url,
                token=token,
            )
        else:
            assert_clean_git_publish_tree(state_repo_dir, check_history=True)

    # Fresh clone verification after push
    with tempfile.TemporaryDirectory() as clone_tmp:
        fresh_clone = Path(clone_tmp) / "fresh_clone"
        _run_git(
            ["clone", "--branch", branch, "--single-branch", clean_url, str(fresh_clone)],
            cwd=Path(clone_tmp),
            remote_url=clean_url,
            token=token,
        )
        clone_audit = assert_clean_git_publish_tree(fresh_clone, check_history=True)
        if resolved_key.strip():
            StateEncryptor(key=resolved_key).verify_bundle_matches_state(
                encrypted_dir=fresh_clone / "encrypted_state",
                expected_state_dir=expected_state_dir,
            )

    return {
        "published": True,
        "branch": branch,
        "orphan_rewritten": needs_orphan_rewrite,
        "fresh_clone_audit": clone_audit,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Isolated Git sync helper for organism-state")
    sub = parser.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="Probe and fetch organism-state safely")
    f.add_argument("--state-repo-dir", required=True)
    f.add_argument("--remote-url", required=True)
    f.add_argument("--encrypted-dir", required=True)
    f.add_argument("--legacy-state-dir", required=True)
    f.add_argument("--branch", default="organism-state")

    p = sub.add_parser("publish", help="Verify bundle, clean-publish to organism-state, and fresh-clone verify")
    p.add_argument("--state-repo-dir", required=True)
    p.add_argument("--remote-url", required=True)
    p.add_argument("--encrypted-dir", required=True)
    p.add_argument("--expected-state-dir", default="")
    p.add_argument("--branch", default="organism-state")
    p.add_argument("--commit-message", default="chore(state): persist encrypted cognitive state")
    p.add_argument("--purge-plaintext-history", default="false")
    p.add_argument("--author-name", default="organism-runner[bot]")
    p.add_argument("--author-email", default="organism-runner[bot]@users.noreply.github.com")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    token = os.environ.get("GH_TOKEN", "").strip() or os.environ.get("GITHUB_TOKEN", "").strip() or None

    try:
        if args.cmd == "fetch":
            res = fetch_state_branch(
                state_repo_dir=Path(args.state_repo_dir),
                remote_url=args.remote_url,
                encrypted_dir=Path(args.encrypted_dir),
                legacy_state_dir=Path(args.legacy_state_dir),
                branch=args.branch,
                token=token,
            )
            github_env = os.environ.get("GITHUB_ENV")
            if github_env:
                with Path(github_env).open("a", encoding="utf-8") as fh:
                    fh.write(f"STATE_BRANCH_EXISTS={'true' if res['branch_exists'] else 'false'}\n")
            print(json.dumps(res, indent=2, ensure_ascii=True))
            return 0

        if args.cmd == "publish":
            purge = str(args.purge_plaintext_history).strip().lower() in {"1", "true", "yes", "on"}
            exp_dir = Path(args.expected_state_dir) if str(args.expected_state_dir).strip() else None
            res = publish_state_branch(
                state_repo_dir=Path(args.state_repo_dir),
                remote_url=args.remote_url,
                encrypted_dir=Path(args.encrypted_dir),
                expected_state_dir=exp_dir,
                branch=args.branch,
                commit_message=args.commit_message,
                purge_plaintext_history=purge,
                token=token,
                author_name=args.author_name,
                author_email=args.author_email,
            )
            print(json.dumps(res, indent=2, ensure_ascii=True))
            return 0
    except (GitSyncError, StateCryptoError) as exc:
        print(json.dumps({"error": _redact_secret(str(exc), token)}), file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
