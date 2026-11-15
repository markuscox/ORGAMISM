#!/usr/bin/env bash
set -euo pipefail

# Safely probe and fetch the `organism-state` branch using transient GH_TOKEN HTTP extraheader auth.
# Distinguishes absent branch (ls-remote exit 2) from authentication/network errors and fails closed.

WORKSPACE_DIR="${WORKSPACE_DIR:-$(pwd)}"
STATE_REPO_DIR="${STATE_REPO_DIR:?STATE_REPO_DIR is required}"
ENCRYPTED_DIR="${ENCRYPTED_DIR:?ENCRYPTED_DIR is required}"
LEGACY_STATE_DIR="${LEGACY_STATE_DIR:?LEGACY_STATE_DIR is required}"
REMOTE_URL="${REMOTE_URL:-$(git -C "$WORKSPACE_DIR" remote get-url origin)}"

PYTHONPATH="${WORKSPACE_DIR}" python3 "${WORKSPACE_DIR}/scripts/git_state_sync.py" fetch \
  --state-repo-dir "$STATE_REPO_DIR" \
  --remote-url "$REMOTE_URL" \
  --encrypted-dir "$ENCRYPTED_DIR" \
  --legacy-state-dir "$LEGACY_STATE_DIR" \
  --branch "organism-state"
