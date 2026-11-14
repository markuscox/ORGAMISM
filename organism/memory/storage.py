"""SQLite persistent memory, checkpoint store, idempotency ledger, and atomic snapshots."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from organism.kernel.contracts import (
    CycleCheckpoint,
    CycleStatus,
    EpistemicType,
    MemoryStatus,
    utc_now_iso,
)
from organism.safety.policy import SecurityPolicy
from organism.safety.validation import IntegrityValidator


class SQLiteMemoryStore:
    """Thread-safe, WAL-enabled SQLite persistence layer for ORGANISM."""

    def __init__(self, db_path: Path, snapshot_path: Path, organism_id: str, version: str) -> None:
        self.db_path = Path(db_path)
        self.snapshot_path = Path(snapshot_path)
        self.organism_id = organism_id
        self.version = version
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self._ensure_identity()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS identity_state (
                    organism_id TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    boot_count INTEGER NOT NULL DEFAULT 0,
                    total_cycles INTEGER NOT NULL DEFAULT 0,
                    active_goals_json TEXT NOT NULL DEFAULT '[]',
                    homeostasis_json TEXT NOT NULL DEFAULT '{}',
                    metacognition_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS checkpoints (
                    cycle_id TEXT PRIMARY KEY,
                    operation_id TEXT NOT NULL UNIQUE,
                    event_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_step INTEGER NOT NULL,
                    checkpoint_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS idempotency_ledger (
                    operation_id TEXT PRIMARY KEY,
                    cycle_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    outcome_summary TEXT NOT NULL,
                    result_hash TEXT NOT NULL,
                    completed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS working_memory (
                    slot_id TEXT PRIMARY KEY,
                    key TEXT NOT NULL UNIQUE,
                    value_json TEXT NOT NULL,
                    priority REAL NOT NULL,
                    epistemic_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    expires_at_cycle INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS episodes (
                    episode_id TEXT PRIMARY KEY,
                    cycle_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    trust_level TEXT NOT NULL,
                    event_content TEXT NOT NULL,
                    action_taken TEXT NOT NULL,
                    outcome_status TEXT NOT NULL,
                    outcome_summary TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS semantic_facts (
                    fact_id TEXT PRIMARY KEY,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object_value TEXT NOT NULL,
                    epistemic_type TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL,
                    source_episode_id TEXT NOT NULL,
                    valid_from TEXT NOT NULL,
                    invalidated_at TEXT,
                    superseded_by TEXT
                );

                CREATE TABLE IF NOT EXISTS kg_edges (
                    edge_id TEXT PRIMARY KEY,
                    source_entity TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    target_entity TEXT NOT NULL,
                    episode_id TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    valid_from TEXT NOT NULL,
                    invalidated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS procedures (
                    proc_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    definition_json TEXT NOT NULL,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS usage_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usage_date TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    requests_used INTEGER NOT NULL DEFAULT 0,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    deterministic_resolutions INTEGER NOT NULL DEFAULT 0,
                    deferred_count INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(usage_date, provider, model_name)
                );

                CREATE TABLE IF NOT EXISTS deferred_queue (
                    queue_id TEXT PRIMARY KEY,
                    operation_id TEXT NOT NULL UNIQUE,
                    event_json TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    next_retry_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS safety_audit (
                    audit_id TEXT PRIMARY KEY,
                    cycle_id TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    rule_triggered TEXT NOT NULL,
                    action_decision TEXT NOT NULL,
                    excerpt TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evaluation_runs (
                    run_id TEXT PRIMARY KEY,
                    suite_name TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    failed INTEGER NOT NULL,
                    total INTEGER NOT NULL,
                    metrics_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def _ensure_identity(self) -> None:
        now = utc_now_iso()
        default_goals = [
            "Maintain internal consistency and epistemic accuracy",
            "Resolve incoming tasks deterministically before spending model tokens",
            "Protect system boundaries and verify predictions against outcomes",
        ]
        default_homeostasis = {
            "uncertainty_pressure": 0.2,
            "consistency_pressure": 0.1,
            "goal_completion_drive": 0.4,
            "resource_conservation_drive": 0.85,
        }
        default_metacognition = {
            "total_predictions": 0,
            "accurate_predictions": 0,
            "calibration_score": 1.0,
            "organ_failures": 0,
            "repeated_mistakes": 0,
        }
        with self._connect() as conn:
            row = conn.execute(
                "SELECT organism_id FROM identity_state WHERE organism_id = ?",
                (self.organism_id,),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO identity_state (
                        organism_id, version, boot_count, total_cycles,
                        active_goals_json, homeostasis_json, metacognition_json, updated_at
                    ) VALUES (?, ?, 1, 0, ?, ?, ?, ?)
                    """,
                    (
                        self.organism_id,
                        self.version,
                        json.dumps(default_goals),
                        json.dumps(default_homeostasis),
                        json.dumps(default_metacognition),
                        now,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE identity_state SET boot_count = boot_count + 1, updated_at = ? WHERE organism_id = ?",
                    (now, self.organism_id),
                )

    def get_identity(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM identity_state WHERE organism_id = ?",
                (self.organism_id,),
            ).fetchone()
        if row is None:
            return {}
        return {
            "organism_id": row["organism_id"],
            "version": row["version"],
            "boot_count": row["boot_count"],
            "total_cycles": row["total_cycles"],
            "active_goals": json.loads(row["active_goals_json"]),
            "homeostasis": json.loads(row["homeostasis_json"]),
            "metacognition": json.loads(row["metacognition_json"]),
            "updated_at": row["updated_at"],
        }

    def update_identity_metrics(
        self,
        increment_cycles: int = 0,
        homeostasis: dict[str, float] | None = None,
        metacognition: dict[str, Any] | None = None,
        active_goals: list[str] | None = None,
    ) -> None:
        current = self.get_identity()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE identity_state
                SET total_cycles = total_cycles + ?,
                    homeostasis_json = ?,
                    metacognition_json = ?,
                    active_goals_json = ?,
                    updated_at = ?
                WHERE organism_id = ?
                """,
                (
                    increment_cycles,
                    json.dumps(homeostasis if homeostasis is not None else current.get("homeostasis", {})),
                    json.dumps(metacognition if metacognition is not None else current.get("metacognition", {})),
                    json.dumps(active_goals if active_goals is not None else current.get("active_goals", [])),
                    utc_now_iso(),
                    self.organism_id,
                ),
            )

    def save_checkpoint(self, checkpoint: CycleCheckpoint) -> None:
        checkpoint.updated_at = utc_now_iso()
        serialized = json.dumps(checkpoint.to_dict(), ensure_ascii=True)
        redacted, _ = SecurityPolicy.redact_secrets(serialized)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO checkpoints (
                    cycle_id, operation_id, event_id, status, current_step,
                    checkpoint_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cycle_id) DO UPDATE SET
                    status = excluded.status,
                    current_step = excluded.current_step,
                    checkpoint_json = excluded.checkpoint_json,
                    updated_at = excluded.updated_at
                """,
                (
                    checkpoint.cycle_id,
                    checkpoint.operation_id,
                    checkpoint.event_id,
                    checkpoint.status.value,
                    checkpoint.current_step,
                    redacted,
                    checkpoint.created_at,
                    checkpoint.updated_at,
                ),
            )
        self.export_snapshot()

    def get_checkpoint(self, cycle_id: str) -> CycleCheckpoint | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT checkpoint_json FROM checkpoints WHERE cycle_id = ?",
                (cycle_id,),
            ).fetchone()
        if row is None:
            return None
        return CycleCheckpoint.from_dict(json.loads(row["checkpoint_json"]))

    def get_latest_interrupted_checkpoint(self) -> CycleCheckpoint | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT checkpoint_json FROM checkpoints
                WHERE status = ?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (CycleStatus.RUNNING.value,),
            ).fetchone()
        if row is None:
            return None
        return CycleCheckpoint.from_dict(json.loads(row["checkpoint_json"]))

    def list_checkpoints(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT checkpoint_json FROM checkpoints
                ORDER BY updated_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [json.loads(r["checkpoint_json"]) for r in rows]

    def check_idempotency(self, operation_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM idempotency_ledger WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def record_idempotency(
        self, operation_id: str, cycle_id: str, status: CycleStatus, outcome_summary: str
    ) -> None:
        redacted_summary, _ = SecurityPolicy.redact_secrets(outcome_summary)
        result_hash = IntegrityValidator.compute_digest(
            {"operation_id": operation_id, "status": status.value, "summary": redacted_summary}
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO idempotency_ledger (
                    operation_id, cycle_id, status, outcome_summary, result_hash, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    cycle_id,
                    status.value,
                    redacted_summary,
                    result_hash,
                    utc_now_iso(),
                ),
            )

    def upsert_working_memory(
        self,
        key: str,
        value: Any,
        priority: float,
        epistemic_type: EpistemicType,
        source: str,
        expires_at_cycle: int,
        capacity: int,
    ) -> None:
        serialized = json.dumps(value, ensure_ascii=True)
        redacted, _ = SecurityPolicy.redact_secrets(serialized)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO working_memory (
                    slot_id, key, value_json, priority, epistemic_type, source, expires_at_cycle, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    priority = excluded.priority,
                    epistemic_type = excluded.epistemic_type,
                    source = excluded.source,
                    expires_at_cycle = excluded.expires_at_cycle
                """,
                (
                    f"wm_{uuid.uuid4().hex[:10]}",
                    key,
                    redacted,
                    float(priority),
                    epistemic_type.value,
                    source,
                    int(expires_at_cycle),
                    utc_now_iso(),
                ),
            )
            # Enforce bounded working memory capacity by evicting lowest-priority items
            rows = conn.execute(
                "SELECT slot_id FROM working_memory ORDER BY priority DESC, created_at DESC"
            ).fetchall()
            if len(rows) > capacity:
                to_delete = [r["slot_id"] for r in rows[capacity:]]
                conn.executemany(
                    "DELETE FROM working_memory WHERE slot_id = ?",
                    [(sid,) for sid in to_delete],
                )

    def expire_working_memory(self, current_cycle_number: int) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM working_memory WHERE expires_at_cycle <= ?",
                (current_cycle_number,),
            )
            return cur.rowcount

    def list_working_memory(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM working_memory ORDER BY priority DESC, created_at DESC"
            ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["value"] = json.loads(item.pop("value_json"))
            out.append(item)
        return out

    def insert_episode(
        self,
        cycle_id: str,
        event_id: str,
        source: str,
        trust_level: str,
        event_content: str,
        action_taken: str,
        outcome_status: str,
        outcome_summary: str,
        metadata: dict[str, Any],
    ) -> str:
        episode_id = f"ep_{uuid.uuid4().hex[:12]}"
        safe_content, _ = SecurityPolicy.redact_secrets(event_content)
        safe_summary, _ = SecurityPolicy.redact_secrets(outcome_summary)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO episodes (
                    episode_id, cycle_id, event_id, source, trust_level,
                    event_content, action_taken, outcome_status, outcome_summary,
                    metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    episode_id,
                    cycle_id,
                    event_id,
                    source,
                    trust_level,
                    safe_content,
                    action_taken,
                    outcome_status,
                    safe_summary,
                    json.dumps(metadata, ensure_ascii=True),
                    utc_now_iso(),
                ),
            )
        return episode_id

    def list_episodes(self, limit: int = 40) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM episodes ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["metadata"] = json.loads(item.pop("metadata_json"))
            out.append(item)
        return out

    def insert_semantic_fact(
        self,
        subject: str,
        predicate: str,
        object_value: str,
        epistemic_type: EpistemicType,
        confidence: float,
        status: MemoryStatus,
        source_episode_id: str,
    ) -> str:
        fact_id = f"fact_{uuid.uuid4().hex[:12]}"
        safe_obj, _ = SecurityPolicy.redact_secrets(object_value)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO semantic_facts (
                    fact_id, subject, predicate, object_value, epistemic_type,
                    confidence, status, source_episode_id, valid_from, invalidated_at, superseded_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    fact_id,
                    subject,
                    predicate,
                    safe_obj,
                    epistemic_type.value,
                    float(confidence),
                    status.value,
                    source_episode_id,
                    utc_now_iso(),
                ),
            )
        return fact_id

    def invalidate_semantic_fact(self, fact_id: str, superseded_by: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE semantic_facts
                SET status = ?, invalidated_at = ?, superseded_by = ?
                WHERE fact_id = ?
                """,
                (MemoryStatus.INVALIDATED.value, utc_now_iso(), superseded_by, fact_id),
            )

    def list_semantic_facts(self, include_invalidated: bool = True, limit: int = 60) -> list[dict[str, Any]]:
        query = "SELECT * FROM semantic_facts"
        if not include_invalidated:
            query += " WHERE invalidated_at IS NULL"
        query += " ORDER BY valid_from DESC LIMIT ?"
        with self._connect() as conn:
            rows = conn.execute(query, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def insert_kg_edge(
        self,
        source_entity: str,
        relation: str,
        target_entity: str,
        episode_id: str,
        confidence: float,
    ) -> str:
        edge_id = f"edge_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO kg_edges (
                    edge_id, source_entity, relation, target_entity,
                    episode_id, confidence, valid_from, invalidated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    edge_id,
                    source_entity,
                    relation,
                    target_entity,
                    episode_id,
                    float(confidence),
                    utc_now_iso(),
                ),
            )
        return edge_id

    def list_kg_edges(self, limit: int = 60) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM kg_edges ORDER BY valid_from DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def upsert_procedure(self, name: str, status: MemoryStatus, definition: dict[str, Any]) -> str:
        proc_id = f"proc_{uuid.uuid4().hex[:10]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO procedures (proc_id, name, status, definition_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    status = excluded.status,
                    definition_json = excluded.definition_json
                """,
                (proc_id, name, status.value, json.dumps(definition, ensure_ascii=True), utc_now_iso()),
            )
        return proc_id

    def list_procedures(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM procedures ORDER BY created_at DESC").fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["definition"] = json.loads(item.pop("definition_json"))
            out.append(item)
        return out

    def record_usage(
        self,
        usage_date: str,
        provider: str,
        model_name: str,
        requests_delta: int = 0,
        prompt_tokens_delta: int = 0,
        completion_tokens_delta: int = 0,
        deterministic_delta: int = 0,
        deferred_delta: int = 0,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO usage_ledger (
                    usage_date, provider, model_name, requests_used,
                    prompt_tokens, completion_tokens, deterministic_resolutions, deferred_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(usage_date, provider, model_name) DO UPDATE SET
                    requests_used = requests_used + excluded.requests_used,
                    prompt_tokens = prompt_tokens + excluded.prompt_tokens,
                    completion_tokens = completion_tokens + excluded.completion_tokens,
                    deterministic_resolutions = deterministic_resolutions + excluded.deterministic_resolutions,
                    deferred_count = deferred_count + excluded.deferred_count
                """,
                (
                    usage_date,
                    provider,
                    model_name,
                    requests_delta,
                    prompt_tokens_delta,
                    completion_tokens_delta,
                    deterministic_delta,
                    deferred_delta,
                ),
            )

    def get_usage_for_date(self, usage_date: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM usage_ledger WHERE usage_date = ?",
                (usage_date,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_usage_ledger(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM usage_ledger ORDER BY usage_date DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def enqueue_deferred(
        self, operation_id: str, event_payload: dict[str, Any], reason: str, next_retry_at: str
    ) -> str:
        queue_id = f"def_{uuid.uuid4().hex[:10]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO deferred_queue (
                    queue_id, operation_id, event_json, reason, retry_count, next_retry_at, status, created_at
                ) VALUES (?, ?, ?, ?, 1, ?, 'PENDING', ?)
                ON CONFLICT(operation_id) DO UPDATE SET
                    retry_count = retry_count + 1,
                    reason = excluded.reason,
                    next_retry_at = excluded.next_retry_at,
                    status = 'PENDING'
                """,
                (
                    queue_id,
                    operation_id,
                    json.dumps(event_payload, ensure_ascii=True),
                    reason,
                    next_retry_at,
                    utc_now_iso(),
                ),
            )
        return queue_id

    def list_deferred(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM deferred_queue ORDER BY created_at DESC"
            ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["event"] = json.loads(item.pop("event_json"))
            out.append(item)
        return out

    def mark_deferred_resolved(self, operation_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE deferred_queue SET status = 'RESOLVED' WHERE operation_id = ?",
                (operation_id,),
            )

    def insert_safety_audit(
        self,
        audit_id: str,
        cycle_id: str,
        severity: str,
        rule_triggered: str,
        action_decision: str,
        excerpt: str,
        created_at: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO safety_audit (
                    audit_id, cycle_id, severity, rule_triggered, action_decision, excerpt, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (audit_id, cycle_id, severity, rule_triggered, action_decision, excerpt, created_at),
            )

    def list_safety_audits(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM safety_audit ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def save_evaluation_run(
        self, suite_name: str, passed: int, failed: int, total: int, metrics: dict[str, Any]
    ) -> str:
        run_id = f"eval_{uuid.uuid4().hex[:10]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO evaluation_runs (run_id, suite_name, passed, failed, total, metrics_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, suite_name, passed, failed, total, json.dumps(metrics, ensure_ascii=True), utc_now_iso()),
            )
        return run_id

    def list_evaluation_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM evaluation_runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["metrics"] = json.loads(item.pop("metrics_json"))
            out.append(item)
        return out

    def export_snapshot(self) -> dict[str, Any]:
        payload = {
            "exported_at": utc_now_iso(),
            "identity": self.get_identity(),
            "latest_checkpoints": self.list_checkpoints(limit=10),
            "working_memory": self.list_working_memory(),
            "deferred_queue": self.list_deferred(),
        }
        signed = IntegrityValidator.sign_snapshot(payload)
        tmp_path = self.snapshot_path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(signed, fh, indent=2, ensure_ascii=True)
        os.replace(tmp_path, self.snapshot_path)
        return signed

    def verify_snapshot_file(self) -> bool:
        if not self.snapshot_path.exists():
            return False
        with self.snapshot_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return IntegrityValidator.verify_snapshot(data)
