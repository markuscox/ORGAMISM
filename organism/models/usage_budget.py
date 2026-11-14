"""Token and request budget manager with daily usage ledger."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from organism.config.settings import OrganismConfig
from organism.memory.storage import SQLiteMemoryStore


def utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class UsageBudgetManager:
    """Enforces daily request, daily token, and per-cycle token caps."""

    def __init__(self, store: SQLiteMemoryStore, config: OrganismConfig) -> None:
        self._store = store
        self._config = config

    def get_today_totals(self) -> dict[str, Any]:
        today = utc_today()
        rows = self._store.get_usage_for_date(today)
        requests_used = sum(r["requests_used"] for r in rows)
        prompt_tokens = sum(r["prompt_tokens"] for r in rows)
        completion_tokens = sum(r["completion_tokens"] for r in rows)
        deterministic = sum(r["deterministic_resolutions"] for r in rows)
        deferred = sum(r["deferred_count"] for r in rows)
        total_tokens = prompt_tokens + completion_tokens

        return {
            "date": today,
            "requests_used": requests_used,
            "daily_request_limit": self._config.daily_request_limit,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "daily_token_limit": self._config.daily_token_limit,
            "cycle_token_limit": self._config.cycle_token_limit,
            "deterministic_resolutions": deterministic,
            "deferred_count": deferred,
            "remaining_tokens": max(0, self._config.daily_token_limit - total_tokens),
            "remaining_requests": max(0, self._config.daily_request_limit - requests_used),
        }

    def can_spend(self, estimated_tokens: int, cycle_tokens_so_far: int = 0) -> tuple[bool, str]:
        totals = self.get_today_totals()
        if totals["requests_used"] >= self._config.daily_request_limit:
            return False, "Daily request budget exhausted"
        if totals["total_tokens"] + estimated_tokens > self._config.daily_token_limit:
            return False, "Daily token budget exhausted"
        if cycle_tokens_so_far + estimated_tokens > self._config.cycle_token_limit:
            return False, "Per-cycle token budget exceeded"
        return True, "Within budget"

    def record_model_call(self, provider: str, model_name: str, prompt_tokens: int, completion_tokens: int) -> None:
        self._store.record_usage(
            usage_date=utc_today(),
            provider=provider,
            model_name=model_name,
            requests_delta=1,
            prompt_tokens_delta=prompt_tokens,
            completion_tokens_delta=completion_tokens,
        )

    def record_deterministic_resolution(self) -> None:
        self._store.record_usage(
            usage_date=utc_today(),
            provider="deterministic",
            model_name="python-symbolic",
            deterministic_delta=1,
        )

    def record_deferred(self) -> None:
        self._store.record_usage(
            usage_date=utc_today(),
            provider=self._config.model_provider,
            model_name=self._config.model_name,
            deferred_delta=1,
        )
