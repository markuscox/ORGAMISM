"""Discrete wake-cycle scheduler supporting resumption and deferred retries."""

from __future__ import annotations

from datetime import datetime, timezone

from organism.kernel.contracts import CognitiveEvent, CycleCheckpoint
from organism.memory.storage import SQLiteMemoryStore


class WakeScheduler:
    """Selects pending interrupted checkpoints or due deferred tasks on wake."""

    def __init__(self, store: SQLiteMemoryStore) -> None:
        self._store = store

    def find_resumable_checkpoint(self) -> CycleCheckpoint | None:
        return self._store.get_latest_interrupted_checkpoint()

    def find_due_deferred_event(self) -> CognitiveEvent | None:
        now = datetime.now(timezone.utc).isoformat()
        for item in self._store.list_deferred():
            if item["status"] == "PENDING" and item["next_retry_at"] <= now:
                return CognitiveEvent.from_dict(item["event"])
        return None
