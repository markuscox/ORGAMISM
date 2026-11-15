"""Typed configuration loader keeping model names and budgets outside business logic."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OrganismConfig:
    organism_id: str
    version: str
    model_provider: str
    model_name: str
    timeout_seconds: int
    max_retries: int
    backoff_base_seconds: float
    daily_token_limit: int
    daily_request_limit: int
    cycle_token_limit: int
    context_char_limit: int
    max_loop_depth: int
    workspace_capacity: int
    working_memory_capacity: int
    working_memory_ttl_cycles: int
    retrieval_top_k: int
    state_dir: Path
    db_path: Path
    snapshot_path: Path
    # Stage 2 adaptive cognition parameters
    memory_decay_rate: float = 0.5
    max_candidate_retention: int = 40
    world_model_prior_alpha: float = 1.0
    world_model_td_lr: float = 0.25
    ewc_lambda: float = 0.5
    replay_batch_size: int = 8
    metacog_abstain_threshold: float = 0.42
    evidence_verify_threshold: float = 0.78
    evidence_min_independent_sources: int = 2


def _deep_get(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def load_config(
    config_path: str | Path | None = None,
    state_dir_override: str | Path | None = None,
) -> OrganismConfig:
    default_file = Path(__file__).with_name("default.json")
    path = Path(config_path) if config_path else default_file
    with path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    env_state_dir = os.environ.get("ORGANISM_STATE_DIR")
    resolved_state_dir = Path(
        state_dir_override
        or env_state_dir
        or _deep_get(raw, "storage", "state_dir", default="state")
    )

    db_filename = _deep_get(raw, "storage", "db_filename", default="organism_state.db")
    snapshot_filename = _deep_get(
        raw, "storage", "snapshot_filename", default="latest_checkpoint.json"
    )

    default_model_name = _deep_get(raw, "model", "model_name", default="gemini-3.8-flash")
    env_model_name = os.environ.get("ORGANISM_MODEL_NAME", "").strip()
    model_name = env_model_name or default_model_name
    daily_token_limit = int(
        os.environ.get(
            "ORGANISM_DAILY_TOKEN_LIMIT",
            _deep_get(raw, "budgets", "daily_token_limit", default=200000),
        )
    )
    daily_request_limit = int(
        os.environ.get(
            "ORGANISM_DAILY_REQUEST_LIMIT",
            _deep_get(raw, "budgets", "daily_request_limit", default=200),
        )
    )
    cycle_token_limit = int(
        os.environ.get(
            "ORGANISM_CYCLE_TOKEN_LIMIT",
            _deep_get(raw, "budgets", "cycle_token_limit", default=25000),
        )
    )

    return OrganismConfig(
        organism_id=_deep_get(raw, "identity", "organism_id", default="organism-stage1-alpha"),
        version=_deep_get(raw, "identity", "version", default="0.2.0-stage2"),
        model_provider=_deep_get(raw, "model", "provider", default="gemini"),
        model_name=model_name,
        timeout_seconds=int(_deep_get(raw, "model", "timeout_seconds", default=20)),
        max_retries=int(_deep_get(raw, "model", "max_retries", default=2)),
        backoff_base_seconds=float(_deep_get(raw, "model", "backoff_base_seconds", default=1.0)),
        daily_token_limit=daily_token_limit,
        daily_request_limit=daily_request_limit,
        cycle_token_limit=cycle_token_limit,
        context_char_limit=int(_deep_get(raw, "budgets", "context_char_limit", default=6000)),
        max_loop_depth=int(_deep_get(raw, "budgets", "max_loop_depth", default=4)),
        workspace_capacity=int(_deep_get(raw, "memory", "workspace_capacity", default=7)),
        working_memory_capacity=int(_deep_get(raw, "memory", "working_memory_capacity", default=12)),
        working_memory_ttl_cycles=int(_deep_get(raw, "memory", "working_memory_ttl_cycles", default=6)),
        retrieval_top_k=int(_deep_get(raw, "memory", "retrieval_top_k", default=5)),
        state_dir=resolved_state_dir,
        db_path=resolved_state_dir / db_filename,
        snapshot_path=resolved_state_dir / snapshot_filename,
        memory_decay_rate=float(_deep_get(raw, "memory", "decay_rate", default=0.5)),
        max_candidate_retention=int(_deep_get(raw, "memory", "max_candidate_retention", default=40)),
        world_model_prior_alpha=float(_deep_get(raw, "stage2", "world_model_prior_alpha", default=1.0)),
        world_model_td_lr=float(_deep_get(raw, "stage2", "world_model_td_lr", default=0.25)),
        ewc_lambda=float(_deep_get(raw, "stage2", "ewc_lambda", default=0.5)),
        replay_batch_size=int(_deep_get(raw, "stage2", "replay_batch_size", default=8)),
        metacog_abstain_threshold=float(_deep_get(raw, "stage2", "metacog_abstain_threshold", default=0.42)),
        evidence_verify_threshold=float(_deep_get(raw, "stage2", "evidence_verify_threshold", default=0.78)),
        evidence_min_independent_sources=int(
            _deep_get(raw, "stage2", "evidence_min_independent_sources", default=2)
        ),
    )
