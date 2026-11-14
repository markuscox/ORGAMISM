"""In-process event bus and deferred work queue."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from organism.kernel.contracts import CognitiveEvent
from organism.memory.storage import SQLiteMemoryStore


class EventBus:
    """Lightweight deterministic pub/sub + persistent deferred queue."""

    def __init__(self, store: SQLiteMemoryStore) -> None:
        self._store = store
        self._subscribers: dict[str, list[Callable[[dict[str, Any]], None]]] = {}

    def subscribe(self, topic: str, handler: Callable[[dict[str, Any]], None]) -> None:
        self._subscribers.setdefault(topic, []).append(handler)

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        for handler in self._subscribers.get(topic, []):
            try:
                handler(payload)
            except Exception:
                # Event listener failure must never break core runtime
                pass

    def defer_event(self, event: CognitiveEvent, reason: str, delay_seconds: int = 300) -> str:
        next_retry = (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).isoformat()
        return self._store.enqueue_deferred(
            operation_id=event.operation_id,
            event_payload=event.to_dict(),
            reason=reason,
            next_retry_at=next_retry,
        )
