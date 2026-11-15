import "dotenv/config";
import express from "express";
import { execFile } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { promisify } from "node:util";
import { createServer as createViteServer } from "vite";

const execFileAsync = promisify(execFile);
const ROOT_DIR = process.cwd();
const STATE_DIR = process.env.ORGANISM_STATE_DIR || path.join(ROOT_DIR, "state");

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

  // Read live persisted ORGANISM state
  app.get("/api/state", async (_req, res) => {
    try {
      const state = await runPythonCli(["status"]);
      res.json(state);
    } catch (err: any) {
      res.status(500).json({ error: err?.message || "Failed to read ORGANISM state" });
    }
  });

  // Trigger a discrete 16-step wake cycle
  app.post("/api/cycle/wake", async (req, res) => {
    try {
      const {
        event,
        source = "web_observatory",
        trust = "trusted_operator",
        eventType = "observation",
        mode = "auto",
        operationId,
        approved = false,
        crashAtStep,
        faultOrgan,
      } = req.body || {};

      if (typeof event !== "string" || !event.trim()) {
        return res.status(400).json({ error: "Event stimulus text is required." });
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
        allowedTrust.has(trust) ? trust : "trusted_operator",
        "--event-type",
        String(eventType).slice(0, 48),
        "--mode",
        allowedModes.has(mode) ? mode : "auto",
      ];

      if (operationId && typeof operationId === "string" && operationId.trim()) {
        args.push("--operation-id", operationId.trim().slice(0, 64));
      }
      if (approved === true) {
        args.push("--approved");
      }
      if (Number.isInteger(crashAtStep) && crashAtStep >= 1 && crashAtStep <= 15) {
        args.push("--crash-at-step", String(crashAtStep));
      }
      if (typeof faultOrgan === "string" && faultOrgan.trim()) {
        args.push("--fault-organ", faultOrgan.trim().slice(0, 48));
      }

      const result = await runPythonCli(args);
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ error: err?.message || "Wake cycle execution failed" });
    }
  });

  // Resume interrupted RUNNING cycle or due DEFERRED event
  app.post("/api/cycle/resume", async (req, res) => {
    try {
      const { cycleId, faultOrgan } = req.body || {};
      const args = ["resume"];
      if (typeof cycleId === "string" && cycleId.trim()) {
        args.push("--cycle-id", cycleId.trim());
      }
      if (typeof faultOrgan === "string" && faultOrgan.trim()) {
        args.push("--fault-organ", faultOrgan.trim());
      }
      const result = await runPythonCli(args);
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ error: err?.message || "Resume cycle failed" });
    }
  });

  // Human approval gate for WAITING cycle
  app.post("/api/cycle/approve", async (req, res) => {
    try {
      const { cycleId, decision } = req.body || {};
      if (typeof cycleId !== "string" || !cycleId.trim()) {
        return res.status(400).json({ error: "cycleId is required." });
      }
      if (decision !== "approve" && decision !== "reject") {
        return res.status(400).json({ error: "decision must be 'approve' or 'reject'." });
      }
      const result = await runPythonCli(["approve", "--cycle-id", cycleId.trim(), "--decision", decision]);
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ error: err?.message || "Approval action failed" });
    }
  });

  // Run automated unittest suite and Stage 1 benchmarks
  app.post("/api/eval/run", async (_req, res) => {
    try {
      const [unitResult, benchmark] = await Promise.all([
        execFileAsync("python3", ["-m", "unittest", "discover", "-s", "organism/tests", "-v"], {
          cwd: ROOT_DIR,
          env: process.env,
          timeout: 30000,
        })
          .then(({ stdout, stderr }) => ({ ok: true, output: `${stdout}\n${stderr}`.trim() }))
          .catch((err) => ({
            ok: false,
            output: `${err?.stdout || ""}\n${err?.stderr || err?.message || ""}`.trim(),
          })),
        runPythonCli(["eval"]),
      ]);

      const state = await runPythonCli(["status"]);
      res.json({ unitResult, benchmark, state });
    } catch (err: any) {
      res.status(500).json({ error: err?.message || "Evaluation run failed" });
    }
  });

  // Execute a safe bounded active-learning probe
  app.post(["/api/experiments/run", "/api/experiment/run"], async (req, res) => {
    try {
      const { experimentId } = req.body || {};
      if (typeof experimentId !== "string" || !experimentId.trim()) {
        return res.status(400).json({ error: "experimentId is required." });
      }
      const result = await runPythonCli(["experiment", "--id", experimentId.trim().slice(0, 64)]);
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ error: err?.message || "Experiment execution failed" });
    }
  });

  // Run controlled forgetting, Fisher EWC anchoring, and replay rehearsal
  app.post("/api/memory/consolidate", async (_req, res) => {
    try {
      const result = await runPythonCli(["consolidate"]);
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ error: err?.message || "Memory consolidation failed" });
    }
  });

  // Trigger EWC-anchored continual learning replay rehearsal
  app.post("/api/continual/replay", async (_req, res) => {
    try {
      const result = await runPythonCli(["replay"]);
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ error: err?.message || "Replay rehearsal failed" });
    }
  });

  // Trigger controlled selective forgetting of stale unverified clutter
  app.post("/api/memory/forget", async (_req, res) => {
    try {
      const result = await runPythonCli(["forget"]);
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ error: err?.message || "Controlled forgetting failed" });
    }
  });

  // Reset local runtime state cleanly for fresh experiment runs
  app.post("/api/state/reset", async (_req, res) => {
    try {
      if (fs.existsSync(STATE_DIR)) {
        for (const entry of fs.readdirSync(STATE_DIR)) {
          if (entry.startsWith("organism_state.db") || entry === "latest_checkpoint.json") {
            fs.rmSync(path.join(STATE_DIR, entry), { force: true });
          }
        }
      }
      const state = await runPythonCli(["status"]);
      res.json(state);
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
