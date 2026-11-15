# ORGANISM — Stage 2 Adaptive Cognitive Kernel & Observatory

ORGANISM is an experimental, modular artificial cognitive system built around discrete, checkpointed 16-step wake cycles, fault-isolated organs, Bayesian/statistical learning, epistemic provenance, token-economy budgets, and security-first boundaries.

It makes **no claim** to consciousness, sentience, or AGI. Stage 2 extends the Stage 1 kernel with verifiable adaptive learning, probabilistic calibration, evidence-gated memory consolidation, curiosity-driven internal probing, ACT-R memory decay, and continual-learning protections.

## Mathematical Models & Data Structures (Stage 2)

1. **Adaptive World Model (`organism/organs/world_model.py`, `world_transitions`, `prediction_history`)**:
   - State-action keys combine `(intent, trust_level, screening_status, approval_gate, memory_bucket)` and action decision (`ABORT_SAFE`, `WAIT_APPROVAL`, `ACT_DETERMINISTIC`, `ACT_WITH_LLM`).
   - Maintains a **Dirichlet-Categorical** posterior $\alpha \in \mathbb{R}_{>0}^5$ over outcome classes `{ok, degraded, blocked, deferred, waiting}` with recency decay ($\gamma = 0.96$) and a **Beta** posterior $(\alpha_{\text{det}}, \beta_{\text{det}})$ for determinism probability.
   - Computes Shannon transition entropy $H(p) = -\sum_k p_k \log_2 p_k$, Brier error term $(1 - p_{\text{actual}})^2$, and Temporal-Difference residual $\delta_t = r_t - \hat{V}(s, a)$ updated via EMA ($\text{lr} = 0.25$).

2. **Genuine Metacognition (`organism/organs/metacognition.py`, `organ_metrics`)**:
   - Tracks rolling **Brier score** $\frac{1}{N}\sum (1 - p_{\text{actual}})^2$ over persisted `prediction_history`.
   - Separates four distinct confidence axes: `prediction_confidence`, `source_confidence`, `memory_confidence`, and `reasoning_confidence`.
   - Computes per-organ `reliability_ema` and average latency (`avg_duration_ms`).
   - Emits explicit epistemic abstention (`refrain_recommended = true`, `refrain_reasons`) when evidence is unknown, source is untrusted & uncorroborated, Brier drift exceeds threshold, or multiple organs degrade.

3. **Evidence-Based Knowledge Lifecycle (`organism/memory/knowledge_graph.py`, `consolidation.py`, `evidence_records`)**:
   - Lifecycle: `OBSERVED -> CANDIDATE -> EVIDENCE_CHECKED -> VERIFIED | REJECTED` (plus `INVALIDATED` and `FORGOTTEN`).
   - Log-odds evidence pooling deduplicates support by `source` so single-source repetition carries `0.0` additional weight and never self-verifies.
   - Untrusted external assertions contradicting `VERIFIED` facts are immediately recorded as `REJECTED`.
   - Hypotheses are capped below verification and never silently converted into verified facts.

4. **Active Learning & Curiosity (`organism/organs/active_learning.py`, `active_experiments`)**:
   - Scores candidate claims and high-entropy transitions using binary/Shannon entropy $H$, Expected Information Gain $\text{EIG} = H_{\text{before}} - \mathbb{E}[H_{\text{after}}]$, deterministic audit cost $c$, and $\text{EVI} = \text{EIG} - c$.
   - Proposes bounded internal audits (`run_safe_experiment`) with zero arbitrary code execution or external side effects.

5. **ACT-R Memory Decay, Sequences & Selective Forgetting (`organism/memory/retrieval.py`, `consolidation.py`)**:
   - Base-level activation $B_i = \ln(\text{access\_count}) - d \ln(1 + \text{age\_hours})$ mapped via logistic sigmoid, reinforced on retrieval (`touch_semantic_fact`).
   - Episodes track causal chain links (`prev_episode_id`, `sequence_index`) and support sequence + temporal window retrieval.
   - Controlled selective forgetting (`FORGOTTEN`) archives excess low-activation unverified clutter while preserving `VERIFIED` facts and episodic history.

6. **Continual Learning Foundation (`organism/memory/continual.py`, `replay_buffer`)**:
   - Prioritized SQLite experience replay (`replay_buffer`) combined with **EWC-inspired Fisher precision anchoring** (`anchor_alpha`, `fisher_precision`) to preserve learned transition beliefs across regime shifts without PyTorch or GPU dependencies.

## Computational Cost, Measured Performance & Known Limitations

- **Token & CPU Cost**: World-model updates, Brier calibration, evidence pooling, EVI active-learning scoring, ACT-R decay, and EWC replay execute purely deterministically in Python/SQLite at **0 LLM tokens** and sub-millisecond per-organ overhead (`< 5 ms` per organ on CPU).
- **Measured Benchmark Baseline**: All Stage 1 (7/7) and Stage 2 (9/9) checks pass (`16/16`, `score = 1.0`, deterministic evaluation Brier score `~0.197`) in isolated SQLite evaluation with longitudinal regression tracking (`evaluation_runs`).
- **Known Limitations**:
  - Lexical overlap retrieval does not yet use dense vector embeddings (planned when local lightweight embeddings are introduced).
  - The Bayesian world model operates over discrete symbolic state-action buckets rather than continuous latent embeddings (neural JEPA/Dreamer-style models remain future stage work).
  - Active learning probes currently verify internal episodic/graph consistency rather than executing external laboratory/API experiments without operator approval.
  - Heuristic EIG cost weights and single-organism serial execution mean distributed worker swarms remain out of scope.

## Setup & Commands

```bash
# 1. Run full Stage 1 + Stage 2 test suite
python3 -m unittest discover -s organism/tests -v

# 2. Run Stage 1 + Stage 2 capability benchmarks (with regression comparison)
python3 main.py eval

# 3. Wake cycle, active-learning probes & continual-learning CLI
python3 main.py wake --event "fact: target_orbit is 420km" --source station_alpha
python3 main.py wake --event "fact: target_orbit is 420km" --source station_beta
python3 main.py experiment --id <experiment_id>
python3 main.py replay
python3 main.py forget
python3 main.py status

# 4. Run Live Web Observatory (Port 3000)
npm install
npm run dev
```
