"""Hybrid Stage 1 memory retrieval combining lexical overlap, epistemic filtering, and recency."""

from __future__ import annotations

import re
from typing import Any

from .storage import SQLiteMemoryStore


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]{2,}", text.lower()))


class MemoryRetriever:
    """Retrieves relevant episodic, semantic, and working memories without requiring vector DBs."""

    def __init__(self, store: SQLiteMemoryStore) -> None:
        self._store = store

    def retrieve(self, query_text: str, top_k: int = 5) -> list[dict[str, Any]]:
        query_tokens = _tokenize(query_text)
        candidates: list[dict[str, Any]] = []

        for wm in self._store.list_working_memory():
            text = f"{wm['key']} {wm['value']}"
            overlap = len(query_tokens & _tokenize(text))
            score = 0.4 * wm["priority"] + (overlap / max(1, len(query_tokens)))
            candidates.append(
                {
                    "layer": "working",
                    "id": wm["slot_id"],
                    "summary": f"{wm['key']}: {wm['value']}",
                    "epistemic_type": wm["epistemic_type"],
                    "source": wm["source"],
                    "score": round(score, 4),
                    "timestamp": wm["created_at"],
                }
            )

        for fact in self._store.list_semantic_facts(include_invalidated=False, limit=100):
            text = f"{fact['subject']} {fact['predicate']} {fact['object_value']}"
            overlap = len(query_tokens & _tokenize(text))
            if overlap > 0 or not query_tokens:
                score = 0.5 * fact["confidence"] + (overlap / max(1, len(query_tokens)))
                candidates.append(
                    {
                        "layer": "semantic",
                        "id": fact["fact_id"],
                        "summary": f"{fact['subject']} {fact['predicate']} {fact['object_value']}",
                        "epistemic_type": fact["epistemic_type"],
                        "source": fact["source_episode_id"],
                        "confidence": fact["confidence"],
                        "score": round(score, 4),
                        "timestamp": fact["valid_from"],
                    }
                )

        for ep in self._store.list_episodes(limit=40):
            text = f"{ep['event_content']} {ep['outcome_summary']}"
            overlap = len(query_tokens & _tokenize(text))
            if overlap > 0:
                score = 0.25 + (overlap / max(1, len(query_tokens)))
                candidates.append(
                    {
                        "layer": "episodic",
                        "id": ep["episode_id"],
                        "summary": f"[{ep['outcome_status']}] {ep['outcome_summary']}",
                        "epistemic_type": "fact",
                        "source": ep["source"],
                        "score": round(score, 4),
                        "timestamp": ep["created_at"],
                    }
                )

        candidates.sort(key=lambda item: item["score"], reverse=True)
        return candidates[:top_k]
