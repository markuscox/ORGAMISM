"""SQLite persistent memory, checkpoint store, Stage 2 world-model transitions, evidence, and replay."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

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
    """Thread-safe, WAL-enabled SQLite persistence layer for ORGANISM (Stage 1 + Stage 2)."""

    def __init__(self, db_path: Path, snapshot_path: Path, organism_id: str, version: str) -> None:
        self.db_path = Path(db_path)
        self.snapshot_path = Path(snapshot_path)
        self.organism_id = organism_id
        self.version = version
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self._migrate_schema()
        self._ensure_identity()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def checkpoint_wal(self) -> None:
        """Flush and truncate SQLite WAL into the main .db file so direct .db backups stay complete."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            conn.commit()
        finally:
            conn.close()

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
                    prev_episode_id TEXT,
                    sequence_index INTEGER NOT NULL DEFAULT 0,
                    session_id TEXT NOT NULL DEFAULT 'default',
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
                    superseded_by TEXT,
                    evidence_count INTEGER NOT NULL DEFAULT 1,
                    contradiction_count INTEGER NOT NULL DEFAULT 0,
                    access_count INTEGER NOT NULL DEFAULT 1,
                    last_accessed_at TEXT,
                    activation_score REAL NOT NULL DEFAULT 0.0,
                    forgotten_at TEXT
                );

                CREATE TABLE IF NOT EXISTS evidence_records (
                    evidence_id TEXT PRIMARY KEY,
                    fact_id TEXT NOT NULL,
                    episode_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    trust_level TEXT NOT NULL,
                    stance TEXT NOT NULL,
                    weight REAL NOT NULL,
                    rationale TEXT NOT NULL,
                    created_at TEXT NOT NULL
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

                CREATE TABLE IF NOT EXISTS world_transitions (
                    state_action_key TEXT PRIMARY KEY,
                    state_key TEXT NOT NULL,
                    action_key TEXT NOT NULL,
                    alpha_counts_json TEXT NOT NULL,
                    det_alpha REAL NOT NULL DEFAULT 1.0,
                    det_beta REAL NOT NULL DEFAULT 1.0,
                    td_error_ema REAL NOT NULL DEFAULT 0.0,
                    avg_tokens_ema REAL NOT NULL DEFAULT 0.0,
                    fisher_precision REAL NOT NULL DEFAULT 0.0,
                    anchor_alpha_json TEXT NOT NULL DEFAULT '{}',
                    sample_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS prediction_history (
                    pred_id TEXT PRIMARY KEY,
                    cycle_id TEXT NOT NULL,
                    state_action_key TEXT NOT NULL,
                    predicted_status TEXT NOT NULL,
                    predicted_prob REAL NOT NULL,
                    actual_status TEXT NOT NULL,
                    matched INTEGER NOT NULL,
                    brier_term REAL NOT NULL,
                    td_error REAL NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS replay_buffer (
                    replay_id TEXT PRIMARY KEY,
                    state_key TEXT NOT NULL,
                    action_key TEXT NOT NULL,
                    observed_status TEXT NOT NULL,
                    observed_det INTEGER NOT NULL,
                    observed_tokens INTEGER NOT NULL,
                    regime_tag TEXT NOT NULL,
                    priority REAL NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS active_experiments (
                    experiment_id TEXT PRIMARY KEY,
                    target_fact_id TEXT,
                    target_key TEXT NOT NULL,
                    hypothesis TEXT NOT NULL,
                    uncertainty_entropy REAL NOT NULL,
                    expected_info_gain REAL NOT NULL,
                    estimated_cost REAL NOT NULL,
                    evi_score REAL NOT NULL,
                    proposed_probe TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_summary TEXT,
                    info_gain_realized REAL,
                    created_at TEXT NOT NULL,
                    executed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS organ_metrics (
                    organ_name TEXT PRIMARY KEY,
                    executions INTEGER NOT NULL DEFAULT 0,
                    successes INTEGER NOT NULL DEFAULT 0,
                    degraded_count INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    avg_duration_ms REAL NOT NULL DEFAULT 0.0,
                    reliability_ema REAL NOT NULL DEFAULT 1.0,
                    updated_at TEXT NOT NULL
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

                CREATE TABLE IF NOT EXISTS telegram_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    last_update_id INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS telegram_processed_updates (
                    update_id INTEGER PRIMARY KEY,
                    processed_at TEXT NOT NULL
                );
                """
            )

    def _migrate_schema(self) -> None:
        """Safely upgrade pre-existing Stage 1 semantic_facts tables if needed."""
        with self._connect() as conn:
            cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(semantic_facts)").fetchall()
            }
            additions = [
                ("evidence_count", "INTEGER NOT NULL DEFAULT 1"),
                ("contradiction_count", "INTEGER NOT NULL DEFAULT 0"),
                ("access_count", "INTEGER NOT NULL DEFAULT 1"),
                ("last_accessed_at", "TEXT"),
                ("activation_score", "REAL NOT NULL DEFAULT 0.0"),
                ("forgotten_at", "TEXT"),
            ]
            for col_name, col_def in additions:
                if col_name not in cols:
                    conn.execute(f"ALTER TABLE semantic_facts ADD COLUMN {col_name} {col_def}")
            ep_cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(episodes)").fetchall()
            }
            if "prev_episode_id" not in ep_cols:
                conn.execute("ALTER TABLE episodes ADD COLUMN prev_episode_id TEXT")
            if "sequence_index" not in ep_cols:
                conn.execute("ALTER TABLE episodes ADD COLUMN sequence_index INTEGER NOT NULL DEFAULT 0")
            if "session_id" not in ep_cols:
                conn.execute("ALTER TABLE episodes ADD COLUMN session_id TEXT NOT NULL DEFAULT 'default'")

    def _ensure_identity(self) -> None:
        now = utc_now_iso()
        default_goals = [
            "Maintain internal consistency and epistemic accuracy",
            "Resolve incoming tasks deterministically before spending model tokens",
            "Improve world-model calibration and verify claims through independent evidence",
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
            "brier_score": 0.0,
            "organ_failures": 0,
            "repeated_mistakes": 0,
            "refrain_recommended": False,
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
                    "UPDATE identity_state SET boot_count = boot_count + 1, version = ?, updated_at = ? WHERE organism_id = ?",
                    (self.version, now, self.organism_id),
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
        session_id: str = "default",
    ) -> str:
        episode_id = f"ep_{uuid.uuid4().hex[:12]}"
        safe_content, _ = SecurityPolicy.redact_secrets(event_content)
        safe_summary, _ = SecurityPolicy.redact_secrets(outcome_summary)
        sess = str(session_id or "default")[:64]
        with self._connect() as conn:
            prev_row = conn.execute(
                "SELECT episode_id, sequence_index FROM episodes ORDER BY sequence_index DESC, created_at DESC LIMIT 1"
            ).fetchone()
            prev_ep_id = prev_row["episode_id"] if prev_row is not None else None
            next_seq = (int(prev_row["sequence_index"]) + 1) if prev_row is not None else 1
            conn.execute(
                """
                INSERT INTO episodes (
                    episode_id, cycle_id, event_id, source, trust_level,
                    event_content, action_taken, outcome_status, outcome_summary,
                    metadata_json, prev_episode_id, sequence_index, session_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    json.dumps(metadata, ensure_ascii=False),
                    prev_ep_id,
                    next_seq,
                    sess,
                    utc_now_iso(),
                ),
            )
        return episode_id

    def list_episodes(self, limit: int = 40, session_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if session_id:
                rows = conn.execute(
                    "SELECT * FROM episodes WHERE session_id = ? ORDER BY sequence_index DESC, created_at DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM episodes ORDER BY sequence_index DESC, created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["metadata"] = json.loads(item.pop("metadata_json"))
            out.append(item)
        return out

    def list_episode_sequence(
        self,
        start_seq: int = 1,
        end_seq: int | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        clauses = ["sequence_index >= ?"]
        params: list[Any] = [int(start_seq)]
        if end_seq is not None:
            clauses.append("sequence_index <= ?")
            params.append(int(end_seq))
        params.append(int(limit))
        where = " AND ".join(clauses)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM episodes WHERE {where} ORDER BY sequence_index ASC, created_at ASC LIMIT ?",
                tuple(params),
            ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["metadata"] = json.loads(item.pop("metadata_json"))
            out.append(item)
        return out

    def list_episodes_in_time_range(
        self,
        start_iso: str,
        end_iso: str,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        return self.list_episodes_chronological(start_iso=start_iso, end_iso=end_iso, limit=limit)

    def list_episodes_chronological(
        self,
        start_iso: str | None = None,
        end_iso: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if start_iso:
            clauses.append("created_at >= ?")
            params.append(start_iso)
        if end_iso:
            clauses.append("created_at <= ?")
            params.append(end_iso)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM episodes {where} ORDER BY sequence_index ASC, created_at ASC LIMIT ?",
                tuple(params),
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
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO semantic_facts (
                    fact_id, subject, predicate, object_value, epistemic_type,
                    confidence, status, source_episode_id, valid_from, invalidated_at, superseded_by,
                    evidence_count, contradiction_count, access_count, last_accessed_at, activation_score, forgotten_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 1, 0, 1, ?, ?, NULL)
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
                    now,
                    now,
                    round(float(confidence), 4),
                ),
            )
        return fact_id

    def update_semantic_fact_lifecycle(
        self,
        fact_id: str,
        status: MemoryStatus | None = None,
        confidence: float | None = None,
        epistemic_type: EpistemicType | None = None,
        evidence_delta: int = 0,
        contradiction_delta: int = 0,
        activation_score: float | None = None,
    ) -> None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM semantic_facts WHERE fact_id = ?",
                (fact_id,),
            ).fetchone()
            if row is None:
                return
            new_status = status.value if status is not None else row["status"]
            new_conf = float(confidence) if confidence is not None else float(row["confidence"])
            new_ep = epistemic_type.value if epistemic_type is not None else row["epistemic_type"]
            new_ev = int(row["evidence_count"]) + evidence_delta
            new_con = int(row["contradiction_count"]) + contradiction_delta
            new_act = float(activation_score) if activation_score is not None else float(row["activation_score"])
            conn.execute(
                """
                UPDATE semantic_facts
                SET status = ?, confidence = ?, epistemic_type = ?,
                    evidence_count = ?, contradiction_count = ?, activation_score = ?
                WHERE fact_id = ?
                """,
                (new_status, new_conf, new_ep, new_ev, new_con, new_act, fact_id),
            )

    def touch_semantic_fact(self, fact_id: str, new_activation: float) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE semantic_facts
                SET access_count = access_count + 1,
                    last_accessed_at = ?,
                    activation_score = ?
                WHERE fact_id = ?
                """,
                (utc_now_iso(), round(float(new_activation), 4), fact_id),
            )

    def mark_fact_forgotten(self, fact_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE semantic_facts
                SET status = ?, forgotten_at = ?
                WHERE fact_id = ?
                """,
                (MemoryStatus.FORGOTTEN.value, utc_now_iso(), fact_id),
            )

    def find_semantic_triple(
        self, subject: str, predicate: str, object_value: str
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM semantic_facts
                WHERE LOWER(subject) = LOWER(?)
                  AND LOWER(predicate) = LOWER(?)
                  AND LOWER(object_value) = LOWER(?)
                  AND invalidated_at IS NULL
                  AND forgotten_at IS NULL
                ORDER BY valid_from DESC LIMIT 1
                """,
                (subject.strip(), predicate.strip(), object_value.strip()),
            ).fetchone()
        return dict(row) if row is not None else None

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

    def list_semantic_facts(
        self,
        include_invalidated: bool = True,
        include_forgotten: bool = False,
        limit: int = 60,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        if not include_invalidated:
            clauses.append("invalidated_at IS NULL")
        if not include_forgotten:
            clauses.append("forgotten_at IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT * FROM semantic_facts {where} ORDER BY valid_from DESC LIMIT ?"
        with self._connect() as conn:
            rows = conn.execute(query, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def insert_evidence_record(
        self,
        fact_id: str,
        episode_id: str,
        source: str,
        trust_level: str,
        stance: str,
        weight: float,
        rationale: str,
    ) -> str:
        evidence_id = f"evd_{uuid.uuid4().hex[:12]}"
        safe_rat, _ = SecurityPolicy.redact_secrets(rationale)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO evidence_records (
                    evidence_id, fact_id, episode_id, source, trust_level,
                    stance, weight, rationale, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    fact_id,
                    episode_id,
                    source,
                    trust_level,
                    stance,
                    float(weight),
                    safe_rat[:300],
                    utc_now_iso(),
                ),
            )
        return evidence_id

    def list_evidence_for_fact(self, fact_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence_records WHERE fact_id = ? ORDER BY created_at ASC",
                (fact_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_recent_evidence(self, limit: int = 40) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence_records ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
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

    # --- Stage 2: World-Model Transitions, Prediction History, Replay, Active Experiments, Organ Metrics ---

    def get_world_transition(self, state_action_key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM world_transitions WHERE state_action_key = ?",
                (state_action_key,),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["alpha_counts"] = json.loads(item.pop("alpha_counts_json"))
        item["anchor_alpha"] = json.loads(item.pop("anchor_alpha_json"))
        return item

    def upsert_world_transition(
        self,
        state_action_key: str,
        state_key: str,
        action_key: str,
        alpha_counts: dict[str, float],
        det_alpha: float,
        det_beta: float,
        td_error_ema: float,
        avg_tokens_ema: float,
        fisher_precision: float,
        anchor_alpha: dict[str, float],
        sample_count: int,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO world_transitions (
                    state_action_key, state_key, action_key, alpha_counts_json,
                    det_alpha, det_beta, td_error_ema, avg_tokens_ema,
                    fisher_precision, anchor_alpha_json, sample_count, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(state_action_key) DO UPDATE SET
                    alpha_counts_json = excluded.alpha_counts_json,
                    det_alpha = excluded.det_alpha,
                    det_beta = excluded.det_beta,
                    td_error_ema = excluded.td_error_ema,
                    avg_tokens_ema = excluded.avg_tokens_ema,
                    fisher_precision = excluded.fisher_precision,
                    anchor_alpha_json = excluded.anchor_alpha_json,
                    sample_count = excluded.sample_count,
                    updated_at = excluded.updated_at
                """,
                (
                    state_action_key,
                    state_key,
                    action_key,
                    json.dumps(alpha_counts, ensure_ascii=True),
                    float(det_alpha),
                    float(det_beta),
                    float(td_error_ema),
                    float(avg_tokens_ema),
                    float(fisher_precision),
                    json.dumps(anchor_alpha, ensure_ascii=True),
                    int(sample_count),
                    utc_now_iso(),
                ),
            )

    def list_world_transitions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM world_transitions ORDER BY sample_count DESC, updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["alpha_counts"] = json.loads(item.pop("alpha_counts_json"))
            item["anchor_alpha"] = json.loads(item.pop("anchor_alpha_json"))
            out.append(item)
        return out

    def insert_prediction_history(
        self,
        cycle_id: str,
        state_action_key: str,
        predicted_status: str,
        predicted_prob: float,
        actual_status: str,
        matched: bool,
        brier_term: float,
        td_error: float,
    ) -> str:
        pred_id = f"prd_{uuid.uuid4().hex[:10]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO prediction_history (
                    pred_id, cycle_id, state_action_key, predicted_status, predicted_prob,
                    actual_status, matched, brier_term, td_error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pred_id,
                    cycle_id,
                    state_action_key,
                    predicted_status,
                    float(predicted_prob),
                    actual_status,
                    1 if matched else 0,
                    float(brier_term),
                    float(td_error),
                    utc_now_iso(),
                ),
            )
        return pred_id

    def list_prediction_history(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM prediction_history ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def insert_replay_experience(
        self,
        state_key: str,
        action_key: str,
        observed_status: str,
        observed_det: bool,
        observed_tokens: int,
        regime_tag: str,
        priority: float,
        max_buffer_size: int = 200,
    ) -> str:
        replay_id = f"rpl_{uuid.uuid4().hex[:10]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO replay_buffer (
                    replay_id, state_key, action_key, observed_status,
                    observed_det, observed_tokens, regime_tag, priority, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    replay_id,
                    state_key,
                    action_key,
                    observed_status,
                    1 if observed_det else 0,
                    int(observed_tokens),
                    regime_tag,
                    float(priority),
                    utc_now_iso(),
                ),
            )
            rows = conn.execute(
                "SELECT replay_id FROM replay_buffer ORDER BY priority DESC, created_at DESC"
            ).fetchall()
            if len(rows) > max_buffer_size:
                to_del = [(r["replay_id"],) for r in rows[max_buffer_size:]]
                conn.executemany("DELETE FROM replay_buffer WHERE replay_id = ?", to_del)
        return replay_id

    def list_replay_buffer(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM replay_buffer ORDER BY priority DESC, created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def upsert_active_experiment(
        self,
        target_fact_id: str | None,
        target_key: str,
        hypothesis: str,
        uncertainty_entropy: float,
        expected_info_gain: float,
        estimated_cost: float,
        evi_score: float,
        proposed_probe: str,
    ) -> str:
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT experiment_id FROM active_experiments WHERE target_key = ? AND status = 'PROPOSED'",
                (target_key,),
            ).fetchone()
            if existing is not None:
                exp_id = existing["experiment_id"]
                conn.execute(
                    """
                    UPDATE active_experiments
                    SET uncertainty_entropy = ?, expected_info_gain = ?,
                        estimated_cost = ?, evi_score = ?, proposed_probe = ?
                    WHERE experiment_id = ?
                    """,
                    (
                        float(uncertainty_entropy),
                        float(expected_info_gain),
                        float(estimated_cost),
                        float(evi_score),
                        proposed_probe,
                        exp_id,
                    ),
                )
                return exp_id

            exp_id = f"exp_{uuid.uuid4().hex[:10]}"
            conn.execute(
                """
                INSERT INTO active_experiments (
                    experiment_id, target_fact_id, target_key, hypothesis,
                    uncertainty_entropy, expected_info_gain, estimated_cost,
                    evi_score, proposed_probe, status, result_summary, info_gain_realized,
                    created_at, executed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PROPOSED', NULL, NULL, ?, NULL)
                """,
                (
                    exp_id,
                    target_fact_id,
                    target_key,
                    hypothesis[:280],
                    float(uncertainty_entropy),
                    float(expected_info_gain),
                    float(estimated_cost),
                    float(evi_score),
                    proposed_probe,
                    utc_now_iso(),
                ),
            )
            return exp_id

    def get_active_experiment(self, experiment_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM active_experiments WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def mark_experiment_executed(
        self, experiment_id: str, result_summary: str, info_gain_realized: float
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE active_experiments
                SET status = 'EXECUTED', result_summary = ?, info_gain_realized = ?, executed_at = ?
                WHERE experiment_id = ?
                """,
                (result_summary[:300], float(info_gain_realized), utc_now_iso(), experiment_id),
            )

    def list_active_experiments(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM active_experiments ORDER BY status ASC, evi_score DESC, created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def record_organ_metric(self, organ_name: str, status: str, duration_ms: float) -> None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM organ_metrics WHERE organ_name = ?",
                (organ_name,),
            ).fetchone()
            ok = 1 if status == "ok" else 0
            deg = 1 if status == "degraded" else 0
            err = 1 if status in {"error", "blocked"} else 0
            if row is None:
                rel = 1.0 if ok else (0.6 if deg else 0.2)
                conn.execute(
                    """
                    INSERT INTO organ_metrics (
                        organ_name, executions, successes, degraded_count, error_count,
                        avg_duration_ms, reliability_ema, updated_at
                    ) VALUES (?, 1, ?, ?, ?, ?, ?, ?)
                    """,
                    (organ_name, ok, deg, err, float(duration_ms), rel, utc_now_iso()),
                )
            else:
                n = int(row["executions"]) + 1
                new_avg = ((float(row["avg_duration_ms"]) * (n - 1)) + float(duration_ms)) / n
                obs_rel = 1.0 if ok else (0.5 if deg else 0.0)
                new_rel = 0.85 * float(row["reliability_ema"]) + 0.15 * obs_rel
                conn.execute(
                    """
                    UPDATE organ_metrics
                    SET executions = ?, successes = successes + ?, degraded_count = degraded_count + ?,
                        error_count = error_count + ?, avg_duration_ms = ?, reliability_ema = ?, updated_at = ?
                    WHERE organ_name = ?
                    """,
                    (n, ok, deg, err, round(new_avg, 3), round(new_rel, 4), utc_now_iso(), organ_name),
                )

    def list_organ_metrics(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM organ_metrics ORDER BY executions DESC, organ_name ASC"
            ).fetchall()
        return [dict(r) for r in rows]

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

    def list_evaluation_runs(self, limit: int = 15) -> list[dict[str, Any]]:
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

    def get_previous_evaluation_run(
        self, suite_name: str, exclude_run_id: str | None = None
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            if exclude_run_id:
                row = conn.execute(
                    """
                    SELECT * FROM evaluation_runs
                    WHERE suite_name = ? AND run_id != ?
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (suite_name, exclude_run_id),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT * FROM evaluation_runs
                    WHERE suite_name = ?
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (suite_name,),
                ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["metrics"] = json.loads(item.pop("metrics_json"))
        return item

    def get_telegram_offset(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT last_update_id FROM telegram_state WHERE id = 1").fetchone()
        return int(row["last_update_id"]) if row is not None else 0

    def save_telegram_offset(self, last_update_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO telegram_state (id, last_update_id, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    last_update_id = MAX(telegram_state.last_update_id, excluded.last_update_id),
                    updated_at = excluded.updated_at
                """,
                (int(last_update_id), utc_now_iso()),
            )
        self.checkpoint_wal()

    def is_telegram_update_processed(self, update_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM telegram_processed_updates WHERE update_id = ?",
                (int(update_id),),
            ).fetchone()
        return row is not None

    def mark_telegram_update_processed(self, update_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO telegram_processed_updates (update_id, processed_at) VALUES (?, ?)",
                (int(update_id), utc_now_iso()),
            )
            # Keep dedup table bounded to 2000 most recent update IDs
            conn.execute(
                """
                DELETE FROM telegram_processed_updates
                WHERE update_id NOT IN (
                    SELECT update_id FROM telegram_processed_updates ORDER BY update_id DESC LIMIT 2000
                )
                """
            )
        self.checkpoint_wal()

    def export_snapshot(self) -> dict[str, Any]:
        payload = {
            "exported_at": utc_now_iso(),
            "identity": self.get_identity(),
            "latest_checkpoints": self.list_checkpoints(limit=10),
            "working_memory": self.list_working_memory(),
            "deferred_queue": self.list_deferred(),
            "world_transitions_count": len(self.list_world_transitions(limit=100)),
        }
        signed = IntegrityValidator.sign_snapshot(payload)
        tmp_path = self.snapshot_path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(signed, fh, indent=2, ensure_ascii=True)
        os.replace(tmp_path, self.snapshot_path)
        self.checkpoint_wal()
        return signed

    def verify_snapshot_file(self) -> bool:
        if not self.snapshot_path.exists():
            return False
        with self.snapshot_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return IntegrityValidator.verify_snapshot(data)
