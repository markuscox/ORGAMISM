# ORGANISM — Stage 3.2: Secure Telegram Interface, Multilingual Cognition, Encrypted Persistence & Verified CI

ORGANISM is an experimental, modular artificial cognitive system built around discrete, checkpointed 16-step wake cycles, fault-isolated organs, Bayesian/statistical learning, epistemic provenance, token-economy budgets, and security-first boundaries.

It makes **no claim** to consciousness, sentience, or AGI. Stage 3 preserves 100% compatibility with Stage 1 & Stage 2 while adding a private owner-only Telegram Bot API interface, authenticated state encryption for public GitHub repositories, multilingual (Russian + English) Unicode cognition and cross-restart dialogue context, audited permission gating, and a Bearer-authenticated Observatory backend.

---

## Stage 3 Architecture Overview

1. **Pure-Stdlib Private Telegram Interface (`organism/integrations/telegram.py`)**:
   - Uses Python's standard library (`urllib.request`, `hmac`, `hashlib`, `json`) against the Telegram Bot API with zero paid server requirements.
   - **Strict Fail-Closed Authorization**: Every incoming update is accepted **only** when `from.id == TELEGRAM_OWNER_ID`, `chat.type == "private"`, `chat.id == TELEGRAM_OWNER_ID`, and `from.is_bot == false`. Unauthorized user messages, group/supergroup/channel messages, and raw Telegram numeric user/chat IDs are rejected before entering cognition and are **never stored** in SQLite memory, checkpoints, or snapshots (sessions map to a one-way SHA-256 opaque ID `tg_<hash>`).
   - **Idempotency & Recovery**: Persists `telegram_state.last_update_id` and deduplicates `update_id` values in `telegram_processed_updates`. Automatically chunks replies > 4000 characters (`<= 4096` Telegram limit) and retries transient network/429/5xx failures while redacting tokens from any error strings.
   - **Commands**: `/start`, `/help`, `/status`, `/memory <text>`, `/wake <text>`, `/approve <cycle_id>`, `/reject <cycle_id>`. All plain RU/EN text routes directly through `CognitiveKernel.run_cycle(...)`.

2. **Authenticated State Encryption & Safe Legacy Migration (`organism/safety/state_crypto.py`)**:
   - Encrypts SQLite (using `sqlite3.Connection.backup()` so WAL journals are merged consistently) + `latest_checkpoint.json` into `encrypted_state/organism_state.fernet` using **Fernet (AES-128-CBC + HMAC-SHA256)** via `cryptography.fernet.Fernet` (with an OpenSSL wire-compatible fallback for restricted local sandboxes).
   - Verifies HMAC signature, inner per-file SHA-256 digests, `PRAGMA integrity_check`, and snapshot SHA-256 inside a temporary directory **before** writing to `state/`.
   - Fails closed (`StateCryptoError` / `InvalidCiphertextError`) on missing/invalid keys or corrupted ciphertext without overwriting existing state. `state-migrate-restore` safely migrates legacy plaintext `state/` databases into encrypted bundles if `.fernet` does not exist yet, and `scripts/publish_encrypted_state.sh` removes tracked `state/` files (`git add -A`), audits `git ls-files` and `git log`, and rewrites `organism-state` into an encrypted-only orphan commit when legacy plaintext commits remain.

3. **Multilingual (Russian + English) Cognition & Persistent Dialogue Context**:
   - `organism/memory/retrieval.py` implements Unicode (`unicodedata`) tokenization and lightweight Russian/English stem matching.
   - `organism/organs/perception.py` detects Russian (`ru`) vs English (`en`) script, extracts RU/EN assertions (`факт:`, `запомни:`, `fact:`, `remember:`), hypotheses (`гипотеза:`, `hypothesis:`), math (`посчитай ...`, `calc: ...`), and recall queries.
   - `organism/organs/reasoning.py` preserves user language, runs `PermissionPolicy.evaluate(trust_level, Capability.CALL_LLM)` immediately before any LLM call (default free-tier model: `gemini-3.8-flash`, overridable via `ORGANISM_MODEL_NAME`), and explicitly separates `[эпизод / не проверено]` dialogue context from `[кандидат]` and `[проверенный факт]`.

4. **Hardened Web Observatory Backend (`server.ts`) & GitHub Actions Workflows**:
   - All mutating/admin routes (`/api/cycle/wake`, `/api/cycle/resume`, `/api/cycle/approve`, `/api/eval/run`, `/api/experiments/run`, `/api/memory/*`, `/api/continual/replay`, `/api/state/reset`, `/api/admin/state`) require `Authorization: Bearer <ORGANISM_ADMIN_TOKEN>` (validated with `crypto.timingSafeEqual`).
   - Inline `approved: true` on `/api/cycle/wake` and `/api/cycle/resume` is rejected (`400`); approvals require an explicit single `cycleId` via `/api/cycle/approve`.
   - Unauthenticated `GET /api/state` exposes aggregate telemetry only (`redacted_private_state: true`) with empty user memory/episode/checkpoint lists.
   - `.github/workflows/telegram_polling.yml` runs every 5 minutes (plus `workflow_dispatch`) using concurrency group `organism-state-persistence`, isolated `$RUNNER_TEMP/state_repo` branch operations, environment-variable argument passing (zero shell interpolation of user input), and zero unencrypted database/message artifacts. `.github/workflows/ci.yml` runs Python tests, benchmarks, workflow validation, and Node.js 22 `npm ci` + `npm run lint` + `npm run build` backed by `package-lock.json`.

---

## First-Launch Setup Guide

### 1. Generate Secrets
Generate a 32-byte URL-safe base64 Fernet encryption key and an admin bearer token:

```bash
python3 main.py keygen
# Alternative without CLI:
python3 -c "import os, base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

### 2. Configure GitHub Actions Secrets
In your GitHub repository (**Settings → Secrets and variables → Actions**), add:
- `TELEGRAM_BOT_TOKEN` — token from `@BotFather` (already created if following Stage 3 setup)
- `TELEGRAM_OWNER_ID` — your numeric private Telegram user ID (already created if following Stage 3 setup)
- `ORGANISM_STATE_ENCRYPTION_KEY` — the Fernet key generated via `python3 main.py keygen`
- `GEMINI_API_KEY` — optional Gemini API key (`gemini-3.8-flash` default; override with `ORGANISM_MODEL_NAME`)
- *(Server / local UI only; not passed to Telegram polling)* `ORGANISM_ADMIN_TOKEN` — strong random bearer secret to unlock the Observatory control UI

### 3. Verify Locally & Run Tests

```bash
# Validate GitHub Actions workflows
python3 scripts/validate_workflows.py

# Run Stage 1 + Stage 2 + Stage 3 test suite
python3 -m unittest discover -s organism/tests -v

# Run Stage 1 + Stage 2 capability benchmarks
python3 main.py eval

# Test encrypted state pack / unpack cycle
ORGANISM_STATE_ENCRYPTION_KEY="$(python3 main.py keygen)" python3 main.py state-pack --verify-no-plaintext

# Clean CI install, TypeScript check, & build on Node 22
npm ci
npm run lint
npm run build
```

---

## Known Limitations

- **Polling Cadence on GitHub Actions**: Scheduled workflows run on ~5-minute cron intervals (subject to GitHub Actions scheduler queue delays), so replies are asynchronous rather than sub-second WebSocket responses.
- **No Dense Vector Embeddings Yet**: Unicode lexical overlap + stemming handles RU/EN keywords deterministically without GPU/network dependencies, but paraphrases with zero shared stems still rely on LLM synthesis when `GEMINI_API_KEY` is configured.
- **Discrete Symbolic World Model**: World-model transitions and EWC replay operate over discrete symbolic state-action buckets rather than continuous latent embeddings.
- **Single-Owner Telegram Scope**: By design, Telegram polling serves a single verified private owner (`TELEGRAM_OWNER_ID`) and drops all multi-user/group/channel traffic.
