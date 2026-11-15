export type CycleStatus = "RUNNING" | "COMPLETED" | "WAITING" | "DEFERRED" | "FAILED_SAFE";

export type TrustLevel = "trusted_operator" | "internal_system" | "untrusted_external";

export type EpistemicType = "fact" | "assumption" | "prediction" | "hypothesis" | "unknown";

export interface StepTrace {
  step_number: number;
  step_name: string;
  organ: string;
  status: "ok" | "degraded" | "blocked" | "skipped" | "error";
  deterministic: boolean;
  tokens_used: number;
  summary: string;
  data: Record<string, unknown>;
  duration_ms: number;
  timestamp: string;
}

export interface CycleCheckpoint {
  cycle_id: string;
  operation_id: string;
  event_id: string;
  current_step: number;
  status: CycleStatus;
  active_goal: string;
  mode: string;
  event_payload: {
    event_id: string;
    operation_id: string;
    source: string;
    trust_level: TrustLevel;
    event_type: string;
    content: string;
    received_at: string;
  };
  workspace_snapshot: Array<{
    slot: number;
    item_id: string;
    layer: string;
    summary: string;
    epistemic_type: EpistemicType;
    salience: number;
    source: string;
    expires_at_cycle: number;
  }>;
  perception_data: Record<string, unknown>;
  plan: Record<string, unknown>;
  prediction: {
    model_source?: string;
    sample_count?: number;
    predicted_probability?: number;
    transition_entropy?: number;
    expected_outcome?: string;
    [key: string]: unknown;
  };
  risk_assessment: Record<string, unknown>;
  executive_decision: Record<string, unknown>;
  action_result: {
    status?: string;
    confidence?: number;
    deterministic?: boolean;
    tokens_used?: number;
    payload?: Record<string, unknown>;
    error?: string | null;
  };
  comparison: {
    td_error?: number;
    brier_term?: number;
    matched?: boolean;
    [key: string]: unknown;
  };
  metacognition: {
    brier_score?: number;
    refrain_recommended?: boolean;
    refrain_reasons?: string[];
    confidence_axes?: {
      prediction_confidence?: number;
      source_confidence?: number;
      memory_confidence?: number;
      reasoning_confidence?: number;
      [key: string]: unknown;
    };
    [key: string]: unknown;
  };
  homeostasis: Record<string, number>;
  active_learning?: Record<string, unknown>;
  step_traces: StepTrace[];
  tokens_used: number;
  outcome_summary: string;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface EpisodicRecord {
  episode_id: string;
  cycle_id: string;
  event_id: string;
  source: string;
  trust_level: TrustLevel;
  event_content: string;
  action_taken: string;
  outcome_status: CycleStatus;
  outcome_summary: string;
  metadata: Record<string, unknown>;
  prev_episode_id?: string | null;
  sequence_index?: number;
  created_at: string;
}

export interface SemanticFact {
  fact_id: string;
  subject: string;
  predicate: string;
  object_value: string;
  epistemic_type: EpistemicType;
  confidence: number;
  status: string;
  source_episode_id: string;
  valid_from: string;
  invalidated_at: string | null;
  superseded_by: string | null;
  evidence_count?: number;
  contradiction_count?: number;
  access_count?: number;
  last_accessed_at?: string | null;
  activation_score?: number;
  forgotten_at?: string | null;
}

export interface EvidenceRecord {
  evidence_id: string;
  fact_id: string;
  episode_id: string;
  source: string;
  trust_level: string;
  stance: string;
  weight: number;
  rationale: string;
  created_at: string;
}

export interface KnowledgeGraphEdge {
  edge_id: string;
  source_entity: string;
  relation: string;
  target_entity: string;
  episode_id: string;
  confidence: number;
  valid_from: string;
  invalidated_at: string | null;
}

export interface WorkingMemorySlot {
  slot_id: string;
  key: string;
  value: unknown;
  priority: number;
  epistemic_type: EpistemicType;
  source: string;
  expires_at_cycle: number;
  created_at: string;
}

export interface WorldTransition {
  state_action_key: string;
  state_key: string;
  action_key: string;
  alpha_counts: Record<string, number>;
  det_alpha: number;
  det_beta: number;
  td_error_ema: number;
  avg_tokens_ema: number;
  fisher_precision: number;
  anchor_alpha: Record<string, number>;
  sample_count: number;
  updated_at: string;
}

export interface PredictionHistoryRow {
  pred_id: string;
  cycle_id: string;
  state_action_key: string;
  predicted_status: string;
  predicted_prob: number;
  actual_status: string;
  matched: number;
  brier_term: number;
  td_error: number;
  created_at: string;
}

export interface ActiveExperiment {
  experiment_id: string;
  target_fact_id: string | null;
  target_key: string;
  hypothesis: string;
  uncertainty_entropy: number;
  expected_info_gain: number;
  estimated_cost: number;
  evi_score: number;
  proposed_probe: string;
  status: string;
  result_summary: string | null;
  info_gain_realized: number | null;
  created_at: string;
  executed_at: string | null;
}

export interface OrganMetric {
  organ_name: string;
  executions: number;
  successes: number;
  degraded_count: number;
  error_count: number;
  avg_duration_ms: number;
  reliability_ema: number;
  updated_at: string;
}

export interface ReplayExperience {
  replay_id: string;
  state_key: string;
  action_key: string;
  observed_status: string;
  observed_det: number;
  observed_tokens: number;
  regime_tag: string;
  priority: number;
  created_at: string;
}

export interface UsageLedgerRow {
  usage_date: string;
  provider: string;
  model_name: string;
  requests_used: number;
  prompt_tokens: number;
  completion_tokens: number;
  deterministic_resolutions: number;
  deferred_count: number;
}

export interface DeferredItem {
  queue_id: string;
  operation_id: string;
  reason: string;
  retry_count: number;
  next_retry_at: string;
  status: string;
  created_at: string;
  event: Record<string, unknown>;
}

export interface SafetyAuditEntry {
  audit_id: string;
  cycle_id: string;
  severity: string;
  rule_triggered: string;
  action_decision: string;
  excerpt: string;
  created_at: string;
}

export interface EvaluationRun {
  run_id: string;
  suite_name: string;
  passed: number;
  failed: number;
  total: number;
  metrics: {
    score: number;
    brier_score?: number;
    checks: Record<string, boolean>;
    llm_calls_during_benchmark?: number;
    historical_comparison?: {
      previous_run_id?: string;
      previous_score?: number | null;
      score_delta?: number;
      regression_detected?: boolean;
    };
  };
  created_at: string;
}

export interface OrganismFullState {
  identity: {
    organism_id: string;
    version: string;
    boot_count: number;
    total_cycles: number;
    active_goals: string[];
    homeostasis: Record<string, number>;
    metacognition: Record<string, unknown>;
    updated_at: string;
  };
  model_config: {
    provider: string;
    model_name: string;
    gemini_configured: boolean;
    workspace_capacity: number;
    working_memory_capacity: number;
  };
  budget_today: {
    date: string;
    requests_used: number;
    daily_request_limit: number;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    daily_token_limit: number;
    cycle_token_limit: number;
    deterministic_resolutions: number;
    deferred_count: number;
    remaining_tokens: number;
    remaining_requests: number;
  };
  usage_ledger: UsageLedgerRow[];
  checkpoints: CycleCheckpoint[];
  episodes: EpisodicRecord[];
  semantic_facts: SemanticFact[];
  kg_edges: KnowledgeGraphEdge[];
  working_memory: WorkingMemorySlot[];
  procedures: Array<{
    proc_id: string;
    name: string;
    status: string;
    definition: Record<string, unknown>;
  }>;
  deferred_queue: DeferredItem[];
  safety_audits: SafetyAuditEntry[];
  evaluation_runs: EvaluationRun[];
  world_transitions: WorldTransition[];
  prediction_history: PredictionHistoryRow[];
  evidence_records: EvidenceRecord[];
  active_experiments: ActiveExperiment[];
  organ_metrics: OrganMetric[];
  replay_buffer: ReplayExperience[];
  replay_buffer_count?: number;
  snapshot_integrity_valid: boolean;
  authenticated?: boolean;
  auth_required?: boolean;
  admin_configured?: boolean;
  redacted_private_state?: boolean;
}
