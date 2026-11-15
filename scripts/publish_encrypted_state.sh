#!/usr/bin/env bash
set -euo pipefail

# Safely publish ONLY encrypted state to the `organism-state` branch inside an isolated checkout directory.
# Never modifies `main`. Uses `git add -A` so deletions of legacy `state/` files are staged and committed.
# If legacy plaintext history exists on `organism-state` (or PURGE_PLAINTEXT_HISTORY=true), creates a clean
# orphan history on `organism-state` AFTER verifying the encrypted bundle, then audits tip + full git log.

WORKSPACE_DIR="${WORKSPACE_DIR:-$(pwd)}"
STATE_REPO_DIR="${STATE_REPO_DIR:?STATE_REPO_DIR is required}"
ENCRYPTED_DIR="${ENCRYPTED_DIR:?ENCRYPTED_DIR is required}"
COMMIT_MESSAGE="${COMMIT_MESSAGE:-chore(state): persist encrypted cognitive state}"
PURGE_PLAINTEXT_HISTORY="${PURGE_PLAINTEXT_HISTORY:-false}"
REMOTE_URL="${REMOTE_URL:-origin}"

if [ ! -f "$ENCRYPTED_DIR/organism_state.fernet" ]; then
  echo "Refusing to publish: encrypted bundle missing at $ENCRYPTED_DIR/organism_state.fernet" >&2
  exit 2
fi

python3 - "$ENCRYPTED_DIR" <<'PYEOF'
import sys
from pathlib import Path
from organism.safety.state_crypto import assert_no_plaintext_in_publish_dir
assert_no_plaintext_in_publish_dir(Path(sys.argv[1]))
PYEOF

cd "$STATE_REPO_DIR"
git config user.name "${GIT_AUTHOR_NAME:-organism-runner[bot]}"
git config user.email "${GIT_AUTHOR_EMAIL:-organism-runner[bot]@users.noreply.github.com}"

HAS_REMOTE_BRANCH=false
OLD_REMOTE_OID=""
if git ls-remote --exit-code --heads "$REMOTE_URL" organism-state >/dev/null 2>&1; then
  HAS_REMOTE_BRANCH=true
  git fetch "$REMOTE_URL" "+refs/heads/organism-state:refs/remotes/origin/organism-state"
  OLD_REMOTE_OID="$(git rev-parse refs/remotes/origin/organism-state)"
  git checkout -B organism-state "$OLD_REMOTE_OID"
fi

NEEDS_ORPHAN_REWRITE=false
if [ "$HAS_REMOTE_BRANCH" = "false" ] || [ "$PURGE_PLAINTEXT_HISTORY" = "true" ]; then
  NEEDS_ORPHAN_REWRITE=true
elif git log HEAD --name-only --pretty=format: | grep -qE '^(state/|.*\.db($|-wal|-shm)|.*\.sqlite|latest_checkpoint\.json$)'; then
  NEEDS_ORPHAN_REWRITE=true
fi

if [ "$NEEDS_ORPHAN_REWRITE" = "true" ]; then
  git checkout --orphan organism-state-clean
  git rm -rf --ignore-unmatch . >/dev/null 2>&1 || true
  find . -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf {} +
  mkdir -p encrypted_state
  cp -r "$ENCRYPTED_DIR"/. encrypted_state/
  git add -A
  python3 "$WORKSPACE_DIR/main.py" state-verify-git-tree --repo-dir "$STATE_REPO_DIR"
  git commit -m "$COMMIT_MESSAGE"
  git branch -M organism-state-clean organism-state
  python3 "$WORKSPACE_DIR/main.py" state-verify-git-tree --repo-dir "$STATE_REPO_DIR" --check-history
  if [ "$HAS_REMOTE_BRANCH" = "true" ]; then
    git push --force-with-lease="refs/heads/organism-state:${OLD_REMOTE_OID}" "$REMOTE_URL" HEAD:refs/heads/organism-state
  else
    git push "$REMOTE_URL" HEAD:refs/heads/organism-state
  fi
else
  git rm -rf --ignore-unmatch state >/dev/null 2>&1 || true
  find . -mindepth 1 -maxdepth 1 ! -name '.git' ! -name 'encrypted_state' -exec rm -rf {} +
  rm -rf encrypted_state
  mkdir -p encrypted_state
  cp -r "$ENCRYPTED_DIR"/. encrypted_state/
  git add -A
  python3 "$WORKSPACE_DIR/main.py" state-verify-git-tree --repo-dir "$STATE_REPO_DIR"
  if ! git diff --cached --quiet; then
    git commit -m "$COMMIT_MESSAGE"
    python3 "$WORKSPACE_DIR/main.py" state-verify-git-tree --repo-dir "$STATE_REPO_DIR" --check-history
    git push "$REMOTE_URL" HEAD:refs/heads/organism-state
  else
    python3 "$WORKSPACE_DIR/main.py" state-verify-git-tree --repo-dir "$STATE_REPO_DIR" --check-history
    echo "No encrypted state changes to commit."
  fi
fi
