"""Cognitive memory retrieval: ACT-R activation decay, episodic sequences, temporal queries, graph traversal, and selective forgetting."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from .storage import SQLiteMemoryStore


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]{2,}", text.lower()))


def compute_actr_activation(
    access_count: int,
    last_accessed_iso: str | None,
    decay_rate: float = 0.5,
    now: datetime | None = None,
) -> float:
    """
    ACT-R-inspired base-level activation:
      B_i = ln(access_count) - d * ln(1 + age_hours)
    Normalized via logistic mapping into (0, 1] for hybrid ranking.
    """
    ref_now = now or datetime.now(timezone.utc)
    age_hours = 0.0
    if last_accessed_iso:
        try:
            dt = datetime.fromisoformat(last_accessed_iso.replace("Z", "+00:00"))
            age_hours = max(0.0, (ref_now - dt).total_seconds() / 3600.0)
        except ValueError:
            age_hours = 0.0
    raw = math.log(max(1, access_count)) - decay_rate * math.log(1.0 + age_hours)
    return round(1.0 / (1.0 + math.exp(-raw)), 4)


class MemoryRetriever:
    """Retrieves relevant episodic, semantic, and working memories with activation decay and sequences."""

    def __init__(self, store: SQLiteMemoryStore, decay_rate: float = 0.5) -> None:
        self._store = store
        self.decay_rate = decay_rate

    def retrieve(self, query_text: str, top_k: int = 5) -> list[dict[str, Any]]:
        query_tokens = _tokenize(query_text)
        candidates: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)

        for wm in self._store.list_working_memory():
            text = f"{wm['key']} {wm['value']}"
            overlap = len(query_tokens & _tokenize(text))
            if overlap > 0 or not query_tokens:
                score = 0.4 * wm["priority"] + (overlap / max(1, len(query_tokens)))
                candidates.append(
                    {
                        "layer": "working",
                        "id": wm["slot_id"],
                        "summary": f"{wm['key']}: {wm['value']}",
                        "epistemic_type": wm["epistemic_type"],
                        "status": "active",
                        "confidence": float(wm["priority"]),
                        "activation": 1.0,
                        "source": wm["source"],
                        "score": round(score, 4),
                        "timestamp": wm["created_at"],
                    }
                )

        for fact in self._store.list_semantic_facts(include_invalidated=False, include_forgotten=False, limit=120):
            if fact["status"] == "rejected":
                continue
            text = f"{fact['subject']} {fact['predicate']} {fact['object_value']}"
            overlap = len(query_tokens & _tokenize(text))
            if overlap > 0 or not query_tokens:
                activation = compute_actr_activation(
                    int(fact.get("access_count", 1)),
                    fact.get("last_accessed_at") or fact.get("valid_from"),
                    decay_rate=self.decay_rate,
                    now=now,
                )
                status_bonus = 0.15 if fact["status"] == "verified" else 0.0
                score = (
                    0.45 * float(fact["confidence"])
                    + 0.2 * activation
                    + status_bonus
                    + (overlap / max(1, len(query_tokens)))
                )
                candidates.append(
                    {
                        "layer": "semantic",
                        "id": fact["fact_id"],
                        "summary": f"{fact['subject']} {fact['predicate']} {fact['object_value']}",
                        "epistemic_type": fact["epistemic_type"],
                        "status": fact["status"],
                        "source": fact["source_episode_id"],
                        "confidence": float(fact["confidence"]),
                        "activation": activation,
                        "score": round(score, 4),
                        "timestamp": fact["valid_from"],
                    }
                )

        for ep in self._store.list_episodes(limit=40):
            text = f"{ep['event_content']} {ep['outcome_summary']}"
            overlap = len(query_tokens & _tokenize(text))
            if overlap > 0:
                activation = compute_actr_activation(1, ep["created_at"], decay_rate=self.decay_rate, now=now)
                score = 0.2 + 0.15 * activation + (overlap / max(1, len(query_tokens)))
                candidates.append(
                    {
                        "layer": "episodic",
                        "id": ep["episode_id"],
                        "summary": f"[{ep['outcome_status']}] {ep['outcome_summary']}",
                        "epistemic_type": "fact",
                        "status": "recorded",
                        "confidence": 0.8,
                        "activation": activation,
                        "source": ep["source"],
                        "score": round(score, 4),
                        "timestamp": ep["created_at"],
                    }
                )

        candidates.sort(key=lambda item: item["score"], reverse=True)
        selected = candidates[:top_k]

        # Reinforce retrieved semantic records (ACT-R spacing/rehearsal effect)
        for item in selected:
            if item["layer"] == "semantic":
                self._store.touch_semantic_fact(item["id"], float(item.get("activation", 0.5)))

        return selected

    def retrieve_episode_sequence(
        self,
        start_iso: str | None = None,
        end_iso: str | None = None,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """Retrieve chronologically ordered episodic sequence (with optional ISO temporal range filter)."""
        return self._store.list_episodes_chronological(
            start_iso=start_iso,
            end_iso=end_iso,
            limit=limit,
        )

    def retrieve_sequence(
        self, start_seq: int = 1, end_seq: int | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Retrieve ordered episodic sequence preserving prev_episode_id causal chain links."""
        return self._store.list_episode_sequence(start_seq=start_seq, end_seq=end_seq, limit=limit)

    def retrieve_temporal_window(
        self, start_iso: str, end_iso: str, limit: int = 40
    ) -> list[dict[str, Any]]:
        """Retrieve episodes falling within an explicit ISO timestamp window."""
        return self._store.list_episodes_in_time_range(start_iso=start_iso, end_iso=end_iso, limit=limit)

    def retrieve_related_concepts(self, entity: str, max_hops: int = 2) -> list[dict[str, Any]]:
        """Breadth-first traversal across temporal knowledge graph edges up to max_hops."""
        seed = entity.strip().lower()
        if not seed:
            return []
        edges = self._store.list_kg_edges(limit=250)
        visited_entities: set[str] = {seed}
        frontier: set[str] = {seed}
        discovered: list[dict[str, Any]] = []
        seen_edge_ids: set[str] = set()

        for hop in range(1, max(1, max_hops) + 1):
            next_frontier: set[str] = set()
            for edge in edges:
                if edge.get("invalidated_at") is not None or edge["edge_id"] in seen_edge_ids:
                    continue
                src = edge["source_entity"].lower()
                tgt = edge["target_entity"].lower()
                if src in frontier or tgt in frontier:
                    seen_edge_ids.add(edge["edge_id"])
                    discovered.append({**edge, "hop": hop})
                    if src not in visited_entities:
                        visited_entities.add(src)
                        next_frontier.add(src)
                    if tgt not in visited_entities:
                        visited_entities.add(tgt)
                        next_frontier.add(tgt)
            if not next_frontier:
                break
            frontier = next_frontier
        return discovered

    def apply_controlled_forgetting(self, max_retain: int = 40) -> dict[str, Any]:
        """
        Controlled selective forgetting: archives REJECTED records and lowest-activation
        unverified CANDIDATE entries beyond max_retain, while preserving VERIFIED facts & episodes.
        """
        facts = self._store.list_semantic_facts(
            include_invalidated=False, include_forgotten=False, limit=300
        )
        now = datetime.now(timezone.utc)
        unverified = [
            f for f in facts if f["status"] in {"candidate", "observed", "rejected"}
        ]
        if len(unverified) <= max_retain and not any(f["status"] == "rejected" for f in unverified):
            return {"forgotten_count": 0, "forgotten_ids": []}

        forgotten_ids: list[str] = []
        remaining: list[tuple[float, dict[str, Any]]] = []
        for f in unverified:
            if f["status"] == "rejected":
                self._store.mark_fact_forgotten(f["fact_id"])
                forgotten_ids.append(f["fact_id"])
                continue
            activation = compute_actr_activation(
                int(f.get("access_count", 1)),
                f.get("last_accessed_at") or f.get("valid_from"),
                decay_rate=self.decay_rate,
                now=now,
            )
            priority = activation + 0.3 * float(f["confidence"])
            remaining.append((priority, f))

        if len(remaining) > max_retain:
            remaining.sort(key=lambda pair: pair[0])
            for _, fact in remaining[: len(remaining) - max_retain]:
                self._store.mark_fact_forgotten(fact["fact_id"])
                forgotten_ids.append(fact["fact_id"])

        return {"forgotten_count": len(forgotten_ids), "forgotten_ids": forgotten_ids}
