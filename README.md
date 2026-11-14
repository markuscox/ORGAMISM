# ORGANISM — Stage 1 Cognitive Kernel & Observatory

ORGANISM is an experimental, modular artificial cognitive system designed around discrete, checkpointed wake cycles, strict fault isolation, epistemic provenance, token-economy budgets, and security-first boundaries.

It is **not** a chatbot wrapper and makes **no claim** to consciousness, sentience, or AGI. Stage 1 delivers a verifiable, testable cognitive kernel ready for incremental research across future stages.

## What Works Today (Stage 1 Implemented Capabilities)

- **Central Cognitive Kernel & 16-Step State Machine** (`organism/kernel/`): Enforces deterministic step progression (`1..16`) and explicit terminal states (`COMPLETED`, `WAITING`, `DEFERRED`, `FAILED_SAFE`).
- **Crash-Safe Checkpoints & Idempotency** (`organism/memory/storage.py`): SQLite WAL storage + SHA-256 signed atomic JSON snapshots (`state/latest_checkpoint.json`). Interrupted `RUNNING` cycles resume cleanly from the last saved step without re-executing completed steps, and duplicate `operation_id` requests are blocked via `idempotency_ledger`.
- **Modular Cognitive Organs** (`organism/organs/`):
  - `PerceptionOrgan`: Normalizes stimuli, classifies intent (`math_computation`, `knowledge_assertion`, `hypothesis_evaluation`, `memory_query`, `analysis`), and tags `untrusted_external` data.
  - `ImmunityOrgan` & `organism/safety/`: Screens prompt-injection patterns, redacts API keys/secrets (`GEMINI_API_KEY`, `AIza...`, `sk-...`, `Bearer ...`), enforces least-privilege capabilities, gates high-impact actions behind human approval (`WAITING`), and prohibits arbitrary code execution.
  - `AttentionOrgan` & `GlobalWorkspaceOrgan`: Salience scoring and capacity-bounded active broadcast (`<= 7` slots).
  - `WorkingMemoryOrgan`, `EpisodicMemoryOrgan`, `SemanticMemoryOrgan`, `ProceduralMemoryOrgan`: Layered memory with Graphiti-inspired temporal fact invalidation and contradiction detection (`organism/memory/knowledge_graph.py`).
  - `ReasoningOrgan`: Deterministic-first execution—uses an AST-whitelisted Python math evaluator (`SafeMathEvaluator`) and symbolic/epistemic logic at zero token cost before consulting the model provider.
  - `PlannerOrgan`, `WorldModelOrgan`, `ExecutiveOrgan`, `MetacognitionOrgan`, `MotivationOrgan`, `LearningOrgan`, `CommunicationOrgan`: Plan decomposition, prediction vs. observation comparison, calibration tracking, bounded operational homeostasis, and episodic-to-semantic staging.
- **Model Provider & Token Economy** (`organism/models/`): Provider-independent `ModelProvider` contract, `GeminiProvider` targeting `gemini-4-hydrogen` via `GEMINI_API_KEY` with exponential backoff, compact `ContextCompiler`, and daily/per-cycle budget enforcement (`UsageBudgetManager`).
- **Automated Verification & Benchmarks** (`organism/tests/`, `organism/evaluation/`): Unit/integration tests and capability benchmarks.
- **GitHub Actions Discrete Wake Runner** (`.github/workflows/organism_cycle.yml`): Restores persistent state from the `organism-state` branch, runs tests, executes resume + wake cycle, and commits updated state back safely.
- **Live Web Observatory** (`server.ts`, `src/`): Interactive React + Express console on port 3000 bridged directly to the Python kernel.

## What Remains Unimplemented (Planned Future Stages)

- **Stage 2–3 Expansions**: Full archival summarization, automated sleep-like offline consolidation loops, and multi-step dependency backtracking.
- **Stage 4–6 Research Extensions**: Neural world models (Dreamer/JEPA-style latent predictors), Active Inference planners, small local classifiers replacing LLM routing, and reinforcement learning sandboxes.
- **Stage 7 External Autonomy**: Controlled external tool adapters beyond internal operations and human-gated command boundaries.

## Setup Instructions

### 1. Environment & Gemini API Secret

Never commit API keys to source files or Git history.

- **Local execution**:
  ```bash
  export GEMINI_API_KEY="your-google-ai-studio-key"
  ```
  If `GEMINI_API_KEY` is omitted, deterministic operations (math, memory queries, assertions, hypothesis framing, safety checks) still execute cleanly at zero token cost, while open-ended synthesis safely falls back to offline deterministic triage.

- **GitHub Actions**:
  1. Keep your repository **private** initially.
  2. Go to **Settings → Secrets and variables → Actions → New repository secret**.
  3. Add `GEMINI_API_KEY` with your Google AI Studio API key.
  4. Ensure **Settings → Actions → General → Workflow permissions** grants **Read and write permissions** so the workflow can maintain the isolated `organism-state` branch.

### 2. Run Automated Tests & Benchmarks

```bash
python3 -m unittest discover -s organism/tests -v
python3 main.py eval
```

### 3. Run Your First Discrete Wake Cycle

```bash
# Deterministic math cycle (0 LLM tokens)
python3 main.py wake --event "calc: (144 / 12) + sqrt(81)" --source cli_operator

# Knowledge assertion + temporal contradiction test
python3 main.py wake --event "fact: target_orbit is 420km" --source cli_operator
python3 main.py wake --event "fact: target_orbit is 435km" --source cli_operator

# Simulated crash at step 7 and process-restart resumption
python3 main.py wake --event "calc: 19 * 3" --crash-at-step 7
python3 main.py resume

# Inspect persisted identity, memories, ledger, and safety log
python3 main.py status
```

### 4. Run the Live Web Observatory (Port 3000)

```bash
npm install
npm run dev
```
