import "dotenv/config";
import crypto from "node:crypto";
import express, { type NextFunction, type Request, type Response } from "express";
import { execFile } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { promisify } from "node:util";
import { createServer as createViteServer } from "vite";

const execFileAsync = promisify(execFile);
const ROOT_DIR = process.cwd();
const STATE_DIR = process.env.ORGANISM_STATE_DIR || path.join(ROOT_DIR, "state");

function resolveAdminToken(): string {
  const raw = (process.env.ORGANISM_ADMIN_TOKEN || "").trim();
  if (!raw || raw === "MY_ORGANISM_ADMIN_TOKEN") {
    return "";
  }
  return raw;
}

function extractBearerToken(req: Request): string {
  const authHeader = req.header("authorization") || "";
  if (authHeader.toLowerCase().startsWith("bearer ")) {
    return authHeader.slice(7).trim();
  }
  return (req.header("x-organism-admin-token") || "").trim();
}

function isAdminAuthorized(req: Request): boolean {
  const configured = resolveAdminToken();
  if (!configured) {
    return false;
  }
  const provided = extractBearerToken(req);
  if (!provided) {
    return false;
  }
  const a = Buffer.from(provided, "utf8");
  const b = Buffer.from(configured, "utf8");
  if (a.length !== b.length) {
    return false;
  }
  return crypto.timingSafeEqual(a, b);
}

function requireAdminAuth(req: Request, res: Response, next: NextFunction) {
  const configured = resolveAdminToken();
  if (!configured) {
    return res.status(503).json({
      error: "Administrative API disabled: ORGANISM_ADMIN_TOKEN is not configured on the server.",
    });
  }
  if (!isAdminAuthorized(req)) {
    return res.status(401).json({
      error: "Unauthorized: valid ORGANISM_ADMIN_TOKEN Bearer token is required.",
    });
  }
  next();
}

function redactPublicState(fullState: any) {
  // Public read-only summary: exposes aggregate telemetry & benchmarks ONLY; zero user messages, memories, or chat history.
  return {
    authenticated: false,
    auth_required: true,
    admin_configured: Boolean(resolveAdminToken()),
    redacted_private_state: true,
    identity: {
      organism_id: fullState.identity?.organism_id || "organism",
      version: fullState.identity?.version || "stage3",
      boot_count: fullState.identity?.boot_count || 0,
      total_cycles: fullState.identity?.total_cycles || 0,
      active_goals: fullState.identity?.active_goals || [],
      homeostasis: fullState.identity?.homeostasis || {},
      metacognition: {
        total_predictions: fullState.identity?.metacognition?.total_predictions || 0,
        accurate_predictions: fullState.identity?.metacognition?.accurate_predictions || 0,
        calibration_score: fullState.identity?.metacognition?.calibration_score ?? 1.0,
        brier_score: fullState.identity?.metacognition?.brier_score ?? 0.0,
        organ_failures: fullState.identity?.metacognition?.organ_failures || 0,
        refrain_recommended: Boolean(fullState.identity?.metacognition?.refrain_recommended),
      },
      updated_at: fullState.identity?.updated_at || "",
    },
    model_config: fullState.model_config,
    budget_today: fullState.budget_today,
    usage_ledger: fullState.usage_ledger || [],
    checkpoints: [],
    episodes: [],
    semantic_facts: [],
    kg_edges: [],
    working_memory: [],
    procedures: [],
    deferred_queue: [],
    safety_audits: [],
    evaluation_runs: fullState.evaluation_runs || [],
    world_transitions: [],
    prediction_history: [],
    evidence_records: [],
    active_experiments: [],
    organ_metrics: fullState.organ_metrics || [],
    replay_buffer: [],
    replay_buffer_count: fullState.replay_buffer_count || 0,
    snapshot_integrity_valid: Boolean(fullState.snapshot_integrity_valid),
  };
}

async function runPythonCli(args: string[]): Promise<any> {
  const { stdout, stderr } = await execFileAsync("python3", ["main.py", "--state-dir", STATE_DIR, ...args], {
    cwd: ROOT_DIR,
    env: process.env,
    timeout: 30000,
    maxBuffer: 1024 * 1024 * 4,
  });
  if (stderr && !stdout.trim()) {
    throw new Error(stderr.trim());
  }
  return JSON.parse(stdout);
}

async function startServer() {
  const app = express();
  app.use(express.json({ limit: "256kb" }));

  // Public health endpoint (no user data)
  app.get("/api/health", (_req, res) => {
    res.json({
      ok: true,
      service: "organism-observatory",
      auth_required: true,
      admin_configured: Boolean(resolveAdminToken()),
    });
  });

  // Read-only state endpoint: returns sanitized summary unless authenticated with ORGANISM_ADMIN_TOKEN
  app.get("/api/state", async (req, res) => {
    try {
      const state = await runPythonCli(["status"]);
      if (isAdminAuthorized(req)) {
        return res.json({
          ...state,
          authenticated: true,
          auth_required: true,
          admin_configured: true,
          redacted_private_state: false,
        });
      }
      return res.json(redactPublicState(state));
    } catch (err: any) {
      res.status(500).json({ error: err?.message || "Failed to read ORGANISM state" });
    }
  });

  // Explicit admin full-state read
  app.get("/api/admin/state", requireAdminAuth, async (_req, res) => {
    try {
      const state = await runPythonCli(["status"]);
      res.json({
        ...state,
        authenticated: true,
        auth_required: true,
        admin_configured: true,
        redacted_private_state: false,
      });
    } catch (err: any) {
      res.status(500).json({ error: err?.message || "Failed to read admin state" });
    }
  });

  // Protected: Trigger a discrete 16-step wake cycle
  // Security invariants: never accept inline `approved=true` or elevate unauthenticated callers.
  app.post("/api/cycle/wake", requireAdminAuth, async (req, res) => {
    try {
      const {
        event,
        source = "web_observatory",
        trust = "untrusted_external",
        eventType = "observation",
        mode = "auto",
        operationId,
        crashAtStep,
        faultOrgan,
      } = req.body || {};

      if (typeof event !== "string" || !event.trim()) {
        return res.status(400).json({ error: "Event stimulus text is required." });
      }
      if ((req.body as any)?.approved === true) {
        return res.status(400).json({
          error: "Inline approved=true is prohibited on /api/cycle/wake; use /api/cycle/approve with explicit cycleId.",
        });
      }

      const allowedTrust = new Set(["trusted_operator", "internal_system", "untrusted_external"]);
      const allowedModes = new Set(["auto", "deterministic_only", "gemini_assisted"]);

      const args = [
        "wake",
        "--event",
        event.trim().slice(0, 4000),
        "--source",
        String(source).slice(0, 64),
        "--trust",
        allowedTrust.has(trust) ? trust : "untrusted_external",
        "--event-type",
        String(eventType).slice(0, 48),
        "--mode",
        allowedModes.has(mode) ? mode : "auto",
      ];

      if (operationId && typeof operationId === "string" && operationId.trim()) {
        args.push("--operation-id", operationId.trim().slice(0, 64));
      }
      if (Number.isInteger(crashAtStep) && crashAtStep >= 1 && crashAtStep <= 15) {
        args.push("--crash-at-step", String(crashAtStep));
      }
      if (typeof faultOrgan === "string" && faultOrgan.trim()) {
        args.push("--fault-organ", faultOrgan.trim().slice(0, 48));
      }

      const result = await runPythonCli(args);
      res.json({
        ...result,
        state: {
          ...result.state,
          authenticated: true,
          auth_required: true,
          admin_configured: true,
          redacted_private_state: false,
        },
      });
    } catch (err: any) {
      res.status(500).json({ error: err?.message || "Wake cycle execution failed" });
    }
  });

  // Protected: Resume interrupted RUNNING cycle or due DEFERRED event (never approves WAITING inline)
  app.post("/api/cycle/resume", requireAdminAuth, async (req, res) => {
    try {
      if ((req.body as any)?.approved === true) {
        return res.status(400).json({
          error: "Inline approved=true is prohibited on /api/cycle/resume; use /api/cycle/approve with explicit cycleId.",
        });
      }
      const { cycleId, faultOrgan } = req.body || {};
      const args = ["resume"];
      if (typeof cycleId === "string" && cycleId.trim()) {
        args.push("--cycle-id", cycleId.trim());
      }
      if (typeof faultOrgan === "string" && faultOrgan.trim()) {
        args.push("--fault-organ", faultOrgan.trim());
      }
      const result = await runPythonCli(args);
      res.json({
        ...result,
        state: result.state
          ? {
              ...result.state,
              authenticated: true,
              auth_required: true,
              admin_configured: true,
              redacted_private_state: false,
            }
          : null,
      });
    } catch (err: any) {
      res.status(500).json({ error: err?.message || "Resume cycle failed" });
    }
  });

  // Protected: Human approval gate bound strictly to one explicit WAITING cycleId
  app.post("/api/cycle/approve", requireAdminAuth, async (req, res) => {
    try {
      const { cycleId, decision } = req.body || {};
      if (
        typeof cycleId !== "string" ||
        !cycleId.trim() ||
        ["all", "*", "any"].includes(cycleId.trim().toLowerCase()) ||
        /\s/.test(cycleId.trim())
      ) {
        return res.status(400).json({ error: "A single explicit cycleId is required." });
      }
      if (decision !== "approve" && decision !== "reject") {
        return res.status(400).json({ error: "decision must be 'approve' or 'reject'." });
      }
      const result = await runPythonCli(["approve", "--cycle-id", cycleId.trim(), "--decision", decision]);
      res.json({
        ...result,
        state: result.state
          ? {
              ...result.state,
              authenticated: true,
              auth_required: true,
              admin_configured: true,
              redacted_private_state: false,
            }
          : null,
      });
    } catch (err: any) {
      res.status(500).json({ error: err?.message || "Approval action failed" });
    }
  });

  // Protected: Run automated unittest suite and benchmarks
  app.post("/api/eval/run", requireAdminAuth, async (_req, res) => {
    try {
      const [unitResult, benchmark] = await Promise.all([
        execFileAsync("python3", ["-m", "unittest", "discover", "-s", "organism/tests", "-v"], {
          cwd: ROOT_DIR,
          env: process.env,
          timeout: 45000,
        })
          .then(({ stdout, stderr }) => ({ ok: true, output: `${stdout}\n${stderr}`.trim() }))
          .catch((err) => ({
            ok: false,
            output: `${err?.stdout || ""}\n${err?.stderr || err?.message || ""}`.trim(),
          })),
        runPythonCli(["eval"]),
      ]);

      const state = await runPythonCli(["status"]);
      res.json({
        unitResult,
        benchmark,
        state: {
          ...state,
          authenticated: true,
          auth_required: true,
          admin_configured: true,
          redacted_private_state: false,
        },
      });
    } catch (err: any) {
      res.status(500).json({ error: err?.message || "Evaluation run failed" });
    }
  });

  // Protected: Execute a safe bounded active-learning probe
  app.post(["/api/experiments/run", "/api/experiment/run"], requireAdminAuth, async (req, res) => {
    try {
      const { experimentId } = req.body || {};
      if (typeof experimentId !== "string" || !experimentId.trim()) {
        return res.status(400).json({ error: "experimentId is required." });
      }
      const result = await runPythonCli(["experiment", "--id", experimentId.trim().slice(0, 64)]);
      res.json({
        ...result,
        state: result.state
          ? {
              ...result.state,
              authenticated: true,
              auth_required: true,
              admin_configured: true,
              redacted_private_state: false,
            }
          : null,
      });
    } catch (err: any) {
      res.status(500).json({ error: err?.message || "Experiment execution failed" });
    }
  });

  // Protected: Memory & continual learning endpoints
  app.post("/api/memory/consolidate", requireAdminAuth, async (_req, res) => {
    try {
      const result = await runPythonCli(["consolidate"]);
      res.json({
        ...result,
        state: result.state
          ? {
              ...result.state,
              authenticated: true,
              auth_required: true,
              admin_configured: true,
              redacted_private_state: false,
            }
          : null,
      });
    } catch (err: any) {
      res.status(500).json({ error: err?.message || "Memory consolidation failed" });
    }
  });

  app.post("/api/continual/replay", requireAdminAuth, async (_req, res) => {
    try {
      const result = await runPythonCli(["replay"]);
      res.json({
        ...result,
        state: result.state
          ? {
              ...result.state,
              authenticated: true,
              auth_required: true,
              admin_configured: true,
              redacted_private_state: false,
            }
          : null,
      });
    } catch (err: any) {
      res.status(500).json({ error: err?.message || "Replay rehearsal failed" });
    }
  });

  app.post("/api/memory/forget", requireAdminAuth, async (_req, res) => {
    try {
      const result = await runPythonCli(["forget"]);
      res.json({
        ...result,
        state: result.state
          ? {
              ...result.state,
              authenticated: true,
              auth_required: true,
              admin_configured: true,
              redacted_private_state: false,
            }
          : null,
      });
    } catch (err: any) {
      res.status(500).json({ error: err?.message || "Controlled forgetting failed" });
    }
  });

  // Protected: Reset local runtime state
  app.post("/api/state/reset", requireAdminAuth, async (_req, res) => {
    try {
      if (fs.existsSync(STATE_DIR)) {
        for (const entry of fs.readdirSync(STATE_DIR)) {
          if (entry.startsWith("organism_state.db") || entry === "latest_checkpoint.json") {
            fs.rmSync(path.join(STATE_DIR, entry), { force: true });
          }
        }
      }
      const state = await runPythonCli(["status"]);
      res.json({
        ...state,
        authenticated: true,
        auth_required: true,
        admin_configured: true,
        redacted_private_state: false,
      });
    } catch (err: any) {
      res.status(500).json({ error: err?.message || "State reset failed" });
    }
  });

  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distDir = path.join(ROOT_DIR, "dist");
    app.use(express.static(distDir));
    app.get("/{*path}", (_req, res) => {
      res.sendFile(path.join(distDir, "index.html"));
    });
  }

  app.listen(3000, "0.0.0.0", () => {
    console.log("ORGANISM Observatory server running on http://0.0.0.0:3000");
  });
}

startServer().catch((err) => {
  console.error("Server failed to start:", err);
  process.exit(1);
});
