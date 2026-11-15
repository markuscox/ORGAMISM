"""Secure Telegram Bot API integration using Python stdlib only."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from organism.kernel.contracts import CognitiveEvent, CycleCheckpoint, CycleStatus, TrustLevel
from organism.kernel.runtime import CognitiveKernel
from organism.organs.perception import detect_language
from organism.safety.policy import SecurityPolicy


class TelegramConfigError(RuntimeError):
    """Raised when required Telegram owner/bot credentials are missing or invalid."""


class TelegramNetworkError(RuntimeError):
    """Raised when Telegram API calls fail after bounded retries."""


@dataclass(frozen=True)
class TelegramAuthResult:
    authorized: bool
    reason: str
    update_id: int
    chat_id: int | None = None
    text: str = ""


def derive_opaque_session_id(owner_id: int | str) -> str:
    """Derive an opaque session identifier so raw Telegram chat/user IDs are never stored in state."""
    digest = hashlib.sha256(f"organism_telegram_session:{owner_id}".encode("utf-8")).hexdigest()[:12]
    return f"tg_{digest}"


def split_telegram_message(text: str, max_len: int = 4000) -> list[str]:
    """
    Split long Telegram replies cleanly at paragraph, newline, or whitespace boundaries
    while strictly respecting Telegram's 4096-char limit and preserving all characters.
    """
    if max_len < 64:
        max_len = 64
    cleaned = text or ""
    if not cleaned:
        return ["(empty response)"]
    if len(cleaned) <= max_len:
        return [cleaned]

    chunks: list[str] = []
    remaining = cleaned
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break

        window = remaining[:max_len]
        split_at = window.rfind("\n\n")
        if split_at < max_len // 3:
            split_at = window.rfind("\n")
        if split_at < max_len // 3:
            split_at = window.rfind(" ")
        if split_at <= 0:
            split_at = max_len

        piece = remaining[:split_at].rstrip()
        if not piece:
            piece = remaining[:max_len]
            split_at = max_len
        chunks.append(piece)
        remaining = remaining[split_at:].lstrip("\n ")
    return chunks


def authorize_telegram_update(update: dict[str, Any], owner_id: int) -> TelegramAuthResult:
    """
    Enforce strict private-owner verification on every incoming Telegram update:
      1. update must contain a standard `message` object
      2. `from.id` must exactly match TELEGRAM_OWNER_ID (and not be a bot)
      3. `chat.type` must be `"private"`
      4. `chat.id` must exactly match TELEGRAM_OWNER_ID
    """
    update_id = int(update.get("update_id", 0))
    msg = update.get("message")
    if not isinstance(msg, dict):
        return TelegramAuthResult(False, "ignored_non_message_update", update_id)

    from_user = msg.get("from")
    chat = msg.get("chat")
    if not isinstance(from_user, dict) or not isinstance(chat, dict):
        return TelegramAuthResult(False, "ignored_missing_sender_or_chat", update_id)

    if bool(from_user.get("is_bot", False)):
        return TelegramAuthResult(False, "ignored_bot_sender", update_id)

    chat_type = str(chat.get("type", ""))
    if chat_type != "private":
        return TelegramAuthResult(False, f"rejected_non_private_chat:{chat_type}", update_id)

    expected = str(int(owner_id))
    from_id_str = str(from_user.get("id", ""))
    chat_id_str = str(chat.get("id", ""))

    if not (
        hmac.compare_digest(from_id_str, expected)
        and hmac.compare_digest(chat_id_str, expected)
    ):
        return TelegramAuthResult(False, "rejected_unauthorized_user", update_id)

    text = str(msg.get("text", "")).strip()
    return TelegramAuthResult(
        authorized=True,
        reason="authorized_owner_private",
        update_id=update_id,
        chat_id=int(owner_id),
        text=text,
    )


class TelegramBotClient:
    """Minimal stdlib HTTPS client for Telegram Bot API with retry, backoff, and token redaction."""

    BASE_URL = "https://api.telegram.org/bot{token}/{method}"

    def __init__(
        self,
        bot_token: str | None = None,
        timeout_seconds: int = 15,
        max_retries: int = 2,
        backoff_base_seconds: float = 0.8,
        opener: Any = None,
    ) -> None:
        raw_token = (bot_token if bot_token is not None else os.environ.get("TELEGRAM_BOT_TOKEN", "")).strip()
        if not raw_token or raw_token == "MY_TELEGRAM_BOT_TOKEN":
            raise TelegramConfigError("TELEGRAM_BOT_TOKEN is missing or not configured.")
        self._token = raw_token
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        self._opener = opener or urllib.request.urlopen

    def _sanitize_error(self, message: str) -> str:
        cleaned = message.replace(self._token, "[REDACTED_TELEGRAM_BOT_TOKEN]")
        cleaned, _ = SecurityPolicy.redact_secrets(cleaned)
        return cleaned

    def _request(self, method: str, payload: dict[str, Any]) -> Any:
        url = self.BASE_URL.format(token=self._token, method=method)
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last_err: Exception | None = None

        for attempt in range(self.max_retries + 1):
            req = urllib.request.Request(
                url,
                data=encoded,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            try:
                with self._opener(req, timeout=self.timeout_seconds) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                if not body.get("ok"):
                    desc = self._sanitize_error(str(body.get("description", "Unknown Telegram API error")))
                    raise TelegramNetworkError(f"Telegram API error ({method}): {desc}")
                return body.get("result")
            except urllib.error.HTTPError as exc:
                raw_detail = exc.read().decode("utf-8", errors="replace")[:240]
                detail = self._sanitize_error(raw_detail)
                if exc.code == 429 and attempt < self.max_retries:
                    retry_after = 1.0
                    try:
                        parsed = json.loads(raw_detail)
                        retry_after = min(10.0, float(parsed.get("parameters", {}).get("retry_after", 1.0)))
                    except Exception:
                        retry_after = self.backoff_base_seconds * (2**attempt)
                    time.sleep(retry_after)
                    last_err = TelegramNetworkError(f"Telegram HTTP 429: {detail}")
                    continue
                if exc.code >= 500 and attempt < self.max_retries:
                    time.sleep(self.backoff_base_seconds * (2**attempt))
                    last_err = TelegramNetworkError(f"Telegram HTTP {exc.code}: {detail}")
                    continue
                raise TelegramNetworkError(f"Telegram HTTP {exc.code} ({method}): {detail}") from None
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                safe_msg = self._sanitize_error(str(exc))
                last_err = TelegramNetworkError(f"Telegram network failure ({method}): {safe_msg}")
                if attempt < self.max_retries:
                    time.sleep(self.backoff_base_seconds * (2**attempt))
                    continue
                raise last_err from None

        raise TelegramNetworkError(f"Telegram request failed after retries: {last_err}")

    def get_updates(
        self,
        offset: int | None = None,
        limit: int = 25,
        timeout: int = 5,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "limit": max(1, min(100, int(limit))),
            "timeout": max(0, min(50, int(timeout))),
            "allowed_updates": ["message"],
        }
        if offset is not None and offset > 0:
            payload["offset"] = int(offset)
        result = self._request("getUpdates", payload)
        return list(result) if isinstance(result, list) else []

    def send_message(self, chat_id: int | str, text: str) -> list[dict[str, Any]]:
        chunks = split_telegram_message(text, max_len=4000)
        sent: list[dict[str, Any]] = []
        total = len(chunks)
        for idx, chunk in enumerate(chunks, start=1):
            body_text = chunk if total == 1 else f"[{idx}/{total}]\n{chunk}"
            if len(body_text) > 4096:
                body_text = body_text[:4096]
            res = self._request(
                "sendMessage",
                {
                    "chat_id": int(chat_id),
                    "text": body_text,
                    "disable_web_page_preview": True,
                },
            )
            if isinstance(res, dict):
                sent.append(res)
        return sent


def parse_owner_id(raw_owner_id: str | int | None = None) -> int:
    raw = str(raw_owner_id if raw_owner_id is not None else os.environ.get("TELEGRAM_OWNER_ID", "")).strip()
    if not raw or raw == "MY_TELEGRAM_OWNER_ID":
        raise TelegramConfigError("TELEGRAM_OWNER_ID is missing or not configured.")
    try:
        val = int(raw)
    except ValueError as exc:
        raise TelegramConfigError("TELEGRAM_OWNER_ID must be a valid integer Telegram user ID.") from exc
    if val <= 0:
        raise TelegramConfigError("TELEGRAM_OWNER_ID must be a positive integer.")
    return val


class TelegramBridge:
    """
    Stateless-process bridge connecting verified Telegram owner messages directly to ORGANISM's CognitiveKernel.
    Does not implement an independent agent; every non-administrative text routes through the 16-step kernel.
    """

    def __init__(
        self,
        kernel: CognitiveKernel,
        client: TelegramBotClient | None = None,
        owner_id: int | str | None = None,
    ) -> None:
        self.kernel = kernel
        self.owner_id = parse_owner_id(owner_id)
        self.client = client or TelegramBotClient()
        self.session_id = derive_opaque_session_id(self.owner_id)

    def _format_cycle_reply(self, cp: CycleCheckpoint, lang: str) -> str:
        status = cp.status.value
        mc = cp.metacognition or {}
        ep_type = str(cp.action_result.get("payload", {}).get("epistemic_type", "unknown"))
        refrain = bool(mc.get("refrain_recommended", False))

        if cp.status == CycleStatus.WAITING:
            if lang == "ru":
                return (
                    f"[ОЖИДАНИЕ ПОДТВЕРЖДЕНИЯ] Цикл {cp.cycle_id}\n"
                    f"{cp.outcome_summary}\n\n"
                    f"Для разрешения выполните:\n/approve {cp.cycle_id}\n"
                    f"Для отклонения:\n/reject {cp.cycle_id}"
                )
            return (
                f"[WAITING APPROVAL] Cycle {cp.cycle_id}\n"
                f"{cp.outcome_summary}\n\n"
                f"To approve this specific cycle:\n/approve {cp.cycle_id}\n"
                f"To reject:\n/reject {cp.cycle_id}"
            )

        if cp.status == CycleStatus.FAILED_SAFE:
            prefix = "[ЗАБЛОКИРОВАНО ПОЛИТИКОЙ]" if lang == "ru" else "[FAILED_SAFE]"
            return f"{prefix} ({cp.cycle_id})\n{cp.outcome_summary}"

        if cp.status == CycleStatus.DEFERRED:
            prefix = "[ОТЛОЖЕНО: ЛИМИТ ТОКЕНОВ]" if lang == "ru" else "[DEFERRED: BUDGET]"
            return f"{prefix} ({cp.cycle_id})\n{cp.outcome_summary}"

        answer = cp.outcome_summary or "Completed"
        if lang == "ru":
            header = f"[{status} | тип={ep_type} | токены={cp.tokens_used}]"
            if refrain:
                reasons = ", ".join(str(r) for r in mc.get("refrain_reasons", []))
                header += f"\nПредупреждение метакогниции: воздержание от уверенного вывода ({reasons})"
            return f"{header}\n{answer}"

        header = f"[{status} | epistemic={ep_type} | tokens={cp.tokens_used}]"
        if refrain:
            reasons = ", ".join(str(r) for r in mc.get("refrain_reasons", []))
            header += f"\nMetacognition abstain advisory: {reasons}"
        return f"{header}\n{answer}"

    def _handle_command(self, text: str, update_id: int) -> str:
        parts = text.split(maxsplit=1)
        cmd = parts[0].split("@", 1)[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""
        lang = detect_language(arg or text)

        if cmd == "/start":
            return (
                "ORGANISM Stage 3 active.\n"
                "Commands:\n"
                "/status — state, calibration & pending approvals\n"
                "/memory <text> — store or query persistent memory\n"
                "/wake <text> — run full 16-step cognitive cycle\n"
                "/approve <cycle_id> — approve a specific WAITING cycle\n"
                "/reject <cycle_id> — reject a specific WAITING cycle\n"
                "/help — show commands\n"
                "Any plain message (Russian or English) enters the ORGANISM cognitive kernel."
            )

        if cmd == "/help":
            return (
                "ORGANISM Commands (zero LLM tokens):\n"
                "/status — identity, Brier calibration, budget, pending cycle_ids\n"
                "/memory <text> — stage candidate memory or query memory\n"
                "/wake <text> — run full 16-step cognitive wake cycle\n"
                "/approve <cycle_id> — approve one specific waiting operation\n"
                "/reject <cycle_id> — reject one specific waiting operation"
            )

        if cmd == "/status":
            st = self.kernel.get_full_state()
            ident = st.get("identity", {})
            mc = ident.get("metacognition", {})
            budget = st.get("budget_today", {})
            waiting = [
                c["cycle_id"]
                for c in st.get("checkpoints", [])
                if c.get("status") == CycleStatus.WAITING.value
            ]
            lines = [
                f"ORGANISM {ident.get('version', 'stage3')}",
                f"Cycles: {ident.get('total_cycles', 0)} | Boots: {ident.get('boot_count', 0)}",
                f"Brier score: {mc.get('brier_score', 0.0)} | Calibration: {mc.get('calibration_score', 1.0)}",
                f"Snapshot SHA-256 valid: {st.get('snapshot_integrity_valid')}",
                f"Tokens today: {budget.get('total_tokens', 0)}/{budget.get('daily_token_limit', 0)} | Requests: {budget.get('requests_used', 0)}/{budget.get('daily_request_limit', 0)}",
                f"Semantic facts: {len(st.get('semantic_facts', []))} | Episodes: {len(st.get('episodes', []))}",
            ]
            if waiting:
                lines.append("Waiting approvals: " + ", ".join(waiting[:5]))
            return "\n".join(lines)

        if cmd in {"/approve", "/reject"}:
            approve_flag = cmd == "/approve"
            if not arg or arg.lower() in {"all", "*", "any"} or " " in arg:
                return (
                    "Rejected: you must specify exactly one cycle_id "
                    "(e.g. /approve cyc_123456). Bulk approval is prohibited."
                )
            existing = self.kernel.store.get_checkpoint(arg)
            if existing is None:
                return f"Cycle '{arg}' not found."
            if existing.status != CycleStatus.WAITING:
                return f"Cycle '{arg}' is in status {existing.status.value}, not WAITING."
            cp = self.kernel.approve_cycle(arg, approve=approve_flag)
            if cp is None:
                return f"Unable to update cycle '{arg}'."
            return f"Cycle {cp.cycle_id} -> {cp.status.value}\n{cp.outcome_summary}"

        if cmd == "/memory":
            if not arg:
                return "Usage: /memory <fact or query text> (e.g. /memory сервер работает в Берлине)"
            lower_arg = arg.lower()
            has_prefix = lower_arg.startswith(
                (
                    "fact:",
                    "факт:",
                    "запомни:",
                    "remember:",
                    "query:",
                    "память:",
                    "вспомни:",
                    "recall:",
                )
            )
            if has_prefix or "?" in arg:
                stimulus = arg
            else:
                stimulus = ("запомни: " if lang == "ru" else "remember: ") + arg
            cp = self._run_kernel_event(stimulus, update_id=update_id, event_type="memory_command")
            return self._format_cycle_reply(cp, detect_language(arg))

        if cmd == "/wake":
            if not arg:
                return "Usage: /wake <stimulus text>"
            cp = self._run_kernel_event(arg, update_id=update_id, event_type="telegram_wake")
            return self._format_cycle_reply(cp, detect_language(arg))

        return (
            "Неизвестная команда. Используйте /help."
            if lang == "ru"
            else "Unknown command. Use /help."
        )

    def _run_kernel_event(
        self,
        text: str,
        update_id: int,
        event_type: str = "telegram_message",
    ) -> CycleCheckpoint:
        ev = CognitiveEvent(
            event_id=f"tg_ev_{update_id}",
            operation_id=f"tg_upd_{update_id}",
            source="telegram_owner",
            trust_level=TrustLevel.TRUSTED_OPERATOR,
            event_type=event_type,
            content=text,
            metadata={
                "session_id": self.session_id,
                "channel": "telegram_private",
            },
        )
        return self.kernel.run_cycle(ev, mode="auto", approved_by_human=False)

    def process_updates(self, updates: list[dict[str, Any]], send_replies: bool = True) -> dict[str, Any]:
        last_offset = self.kernel.store.get_telegram_offset()
        max_seen_offset = last_offset
        processed_count = 0
        ignored_count = 0
        duplicate_count = 0
        cycle_ids: list[str] = []
        errors: list[str] = []

        for update in sorted(updates, key=lambda u: int(u.get("update_id", 0))):
            u_id = int(update.get("update_id", 0))
            if u_id <= 0:
                continue

            if self.kernel.store.is_telegram_update_processed(u_id) or u_id <= last_offset:
                duplicate_count += 1
                max_seen_offset = max(max_seen_offset, u_id)
                continue

            auth = authorize_telegram_update(update, self.owner_id)
            if not auth.authorized:
                # Strict isolation: NEVER persist stranger text, chat IDs, or usernames in memory
                ignored_count += 1
                self.kernel.store.mark_telegram_update_processed(u_id)
                max_seen_offset = max(max_seen_offset, u_id)
                continue

            if not auth.text:
                self.kernel.store.mark_telegram_update_processed(u_id)
                max_seen_offset = max(max_seen_offset, u_id)
                continue

            if auth.text.startswith("/"):
                reply_text = self._handle_command(auth.text, update_id=u_id)
            else:
                cp = self._run_kernel_event(auth.text, update_id=u_id)
                cycle_ids.append(cp.cycle_id)
                reply_text = self._format_cycle_reply(cp, detect_language(auth.text))

            if send_replies and auth.chat_id is not None:
                try:
                    self.client.send_message(auth.chat_id, reply_text)
                except TelegramNetworkError as exc:
                    # Preserve error without losing kernel state; do NOT mark offset past failed reply unless idempotency handles retry
                    errors.append(str(exc))
                    continue

            self.kernel.store.mark_telegram_update_processed(u_id)
            max_seen_offset = max(max_seen_offset, u_id)
            processed_count += 1

        if max_seen_offset > last_offset:
            self.kernel.store.save_telegram_offset(max_seen_offset)
        self.kernel.store.export_snapshot()

        return {
            "processed": processed_count,
            "ignored_unauthorized": ignored_count,
            "duplicates_skipped": duplicate_count,
            "last_offset": self.kernel.store.get_telegram_offset(),
            "cycle_ids": cycle_ids,
            "errors": errors,
        }

    def poll_once(self, limit: int = 25, timeout: int = 5) -> dict[str, Any]:
        """Fetch updates once from Telegram Bot API and process authorized owner messages safely."""
        last_offset = self.kernel.store.get_telegram_offset()
        next_offset = (last_offset + 1) if last_offset > 0 else None
        updates = self.client.get_updates(offset=next_offset, limit=limit, timeout=timeout)
        return self.process_updates(updates, send_replies=True)
