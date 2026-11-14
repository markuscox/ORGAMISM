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
  prediction: Record<string, unknown>;
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
  comparison: Record<string, unknown>;
  metacognition: Record<string, unknown>;
  homeostasis: Record<string, number>;
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
    checks: Record<string, boolean>;
    llm_calls_during_benchmark?: number;
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
  snapshot_integrity_valid: boolean;
}
