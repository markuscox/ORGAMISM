#!/usr/bin/env bash
set -euo pipefail

# Safely publish ONLY encrypted state to the `organism-state` branch inside an isolated checkout directory.
# Never modifies `main`. Uses transient HTTP extraheader auth (never writes tokens to remote URL or config).
# Verifies bundle decryption + SQLite integrity + state comparison BEFORE any history rewrite,
# audits tip + full git log, and re-verifies via a fresh clone after push.

WORKSPACE_DIR="${WORKSPACE_DIR:-$(pwd)}"
STATE_REPO_DIR="${STATE_REPO_DIR:?STATE_REPO_DIR is required}"
ENCRYPTED_DIR="${ENCRYPTED_DIR:?ENCRYPTED_DIR is required}"
EXPECTED_STATE_DIR="${ORGANISM_STATE_DIR:-}"
COMMIT_MESSAGE="${COMMIT_MESSAGE:-chore(state): persist encrypted cognitive state}"
PURGE_PLAINTEXT_HISTORY="${PURGE_PLAINTEXT_HISTORY:-false}"
REMOTE_URL="${REMOTE_URL:-}"

if [ -z "$REMOTE_URL" ]; then
  if git -C "$STATE_REPO_DIR" remote get-url origin >/dev/null 2>&1; then
    REMOTE_URL="$(git -C "$STATE_REPO_DIR" remote get-url origin)"
  else
    REMOTE_URL="$(git -C "$WORKSPACE_DIR" remote get-url origin)"
  fi
fi

if [ ! -f "$ENCRYPTED_DIR/organism_state.fernet" ]; then
  echo "Refusing to publish: encrypted bundle missing at $ENCRYPTED_DIR/organism_state.fernet" >&2
  exit 2
fi

PYTHONPATH="${WORKSPACE_DIR}" python3 "${WORKSPACE_DIR}/scripts/git_state_sync.py" publish \
  --state-repo-dir "$STATE_REPO_DIR" \
  --remote-url "$REMOTE_URL" \
  --encrypted-dir "$ENCRYPTED_DIR" \
  --expected-state-dir "$EXPECTED_STATE_DIR" \
  --branch "organism-state" \
  --commit-message "$COMMIT_MESSAGE" \
  --purge-plaintext-history "$PURGE_PLAINTEXT_HISTORY" \
  --author-name "${GIT_AUTHOR_NAME:-organism-runner[bot]}" \
  --author-email "${GIT_AUTHOR_EMAIL:-organism-runner[bot]@users.noreply.github.com}"
