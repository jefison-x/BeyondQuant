import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import { toNodeHandler } from "@modelcontextprotocol/node";
import { createMcpHandler, McpServer } from "@modelcontextprotocol/server";
import { z } from "zod";

import { fetchByqHealth } from "./backend-health.js";
import {
  fetchByqBacktestCancel,
  fetchByqBacktestGet,
  fetchByqBacktestRun,
  fetchByqBacktestSubmit,
  type BacktestRequest,
} from "./backtest.js";
import { fetchByqFactorCompute, type FactorComputeRequest } from "./factor-research.js";
import {
  fetchByqStrategyApprove,
  fetchByqStrategyExport,
  fetchByqStrategyValidate,
  fetchByqStrategyVersionCreate,
  type StrategyRequest,
} from "./strategy.js";
import { fetchByqMarketDaily, type MarketDailyRequest } from "./market-data.js";
import {
  fetchByqArtifactCreate,
  fetchByqExperimentCreate,
  fetchByqResearchGet,
  fetchByqResearchTaskCreate,
  fetchByqResearchTransition,
  type ArtifactCreateRequest,
  type ExperimentCreateRequest,
  type ResearchEntityType,
  type ResearchTaskCreateRequest,
  type ResearchTransitionRequest,
} from "./research.js";

const SERVICE = "beyondquant-mcp";
const VERSION = "0.1.0";
const PORT = Number(process.env.PORT ?? "8300");
const MCP_PATH = "/mcp/v1";
const BACKEND_URL = process.env.BYQ_BACKEND_URL ?? "http://backend:8000";
const MCP_TOKEN = process.env.BYQ_MCP_TOKEN;

if (!MCP_TOKEN) {
  throw new Error("BYQ_MCP_TOKEN is required to start the MCP service");
}

function healthPayload(): Record<string, string> {
  return { service: SERVICE, status: "ok", version: VERSION };
}

function writeJson(response: ServerResponse, statusCode: number, payload: unknown): void {
  const body = JSON.stringify(payload);
  response.writeHead(statusCode, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
  });
  response.end(body);
}

function authorized(request: IncomingMessage): boolean {
  return request.headers.authorization === `Bearer ${MCP_TOKEN}`;
}

async function byqHealth() {
  return fetchByqHealth(BACKEND_URL);
}

async function byqBacktestSubmit(args: BacktestRequest) {
  return fetchByqBacktestSubmit(BACKEND_URL, args ?? {});
}

async function byqBacktestGet(args: { job_id: string }) {
  return fetchByqBacktestGet(BACKEND_URL, args.job_id);
}

async function byqBacktestRun(args: { job_id: string }) {
  return fetchByqBacktestRun(BACKEND_URL, args.job_id);
}

async function byqBacktestCancel(args: { job_id: string }) {
  return fetchByqBacktestCancel(BACKEND_URL, args.job_id);
}

async function byqMarketDaily(args: MarketDailyRequest) {
  return fetchByqMarketDaily(BACKEND_URL, args ?? {});
}

async function byqFactorCompute(args: FactorComputeRequest) {
  return fetchByqFactorCompute(BACKEND_URL, args ?? {});
}

async function byqStrategyValidate(args: StrategyRequest) {
  return fetchByqStrategyValidate(BACKEND_URL, args ?? {});
}

async function byqStrategyVersionCreate(args: StrategyRequest) {
  return fetchByqStrategyVersionCreate(BACKEND_URL, args ?? {});
}

async function byqStrategyApprove(args: StrategyRequest) {
  return fetchByqStrategyApprove(BACKEND_URL, args ?? {});
}

async function byqStrategyExport(args: { artifact_id: string }) {
  return fetchByqStrategyExport(BACKEND_URL, args.artifact_id);
}

async function byqResearchTaskCreate(args: ResearchTaskCreateRequest) {
  return fetchByqResearchTaskCreate(BACKEND_URL, args);
}

async function byqResearchGet(args: { entity_type: ResearchEntityType; entity_id: string }) {
  return fetchByqResearchGet(BACKEND_URL, args.entity_type, args.entity_id);
}

async function byqResearchTransition(args: ResearchTransitionRequest) {
  return fetchByqResearchTransition(BACKEND_URL, args);
}

async function byqExperimentCreate(args: ExperimentCreateRequest) {
  return fetchByqExperimentCreate(BACKEND_URL, args);
}

async function byqArtifactCreate(args: ArtifactCreateRequest) {
  return fetchByqArtifactCreate(BACKEND_URL, args);
}

function buildServer(): McpServer {
  const server = new McpServer({ name: SERVICE, version: VERSION });
  server.registerTool(
    "byq_health",
    {
      description: "Return BeyondQuant MCP and Backend health status.",
      inputSchema: {},
    },
    byqHealth,
  );
  server.registerTool(
    "byq_market_daily",
    {
      description: "Return BYQ-normalized unadjusted A-share daily bars with provenance.",
      inputSchema: {
        ts_code: z.string().optional().describe("One A-share code such as 000001.SZ."),
        trade_date: z.string().optional().describe("Exact YYYYMMDD trade date."),
        start_date: z.string().optional().describe("Inclusive YYYYMMDD start date."),
        end_date: z.string().optional().describe("Inclusive YYYYMMDD end date."),
      },
    },
    byqMarketDaily,
  );
  server.registerTool(
    "byq_backtest_submit",
    {
      description: "Queue a validated strategy version against a frozen universe and deterministic input snapshot.",
      inputSchema: {
        task_id: z.string(),
        experiment_id: z.string().optional(),
        strategy_version_artifact_id: z.string(),
        approval_artifact_id: z.string(),
        trace_id: z.string(),
        idempotency_key: z.string(),
        universe: z.object({
          universe_id: z.string().optional(),
          version_id: z.string(),
          membership_fingerprint: z.string(),
          symbols: z.array(z.string()).min(1),
        }),
        bars: z.array(z.object({
          symbol: z.string(), trade_date: z.string(), open: z.number(), high: z.number(), low: z.number(), close: z.number(),
          volume: z.number().optional(), prev_close: z.number().optional(), is_suspended: z.boolean().optional(),
          up_limit: z.number().optional(), down_limit: z.number().optional(),
        })).min(1),
        signals: z.array(z.object({
          symbol: z.string(), trade_date: z.string(), side: z.union([z.enum(["buy", "sell", "hold"]), z.number()]), quantity: z.number().int().positive().optional(),
        })),
        execution: z.record(z.string(), z.unknown()).optional(),
        corporate_actions: z.array(z.record(z.string(), z.unknown())).optional(),
      },
    },
    byqBacktestSubmit,
  );
  server.registerTool(
    "byq_backtest_get",
    { description: "Read durable BYQ backtest job state and immutable result reference.", inputSchema: { job_id: z.string() } },
    byqBacktestGet,
  );
  server.registerTool(
    "byq_backtest_run",
    { description: "Run one queued deterministic BYQ backtest job through the worker boundary.", inputSchema: { job_id: z.string() } },
    byqBacktestRun,
  );
  server.registerTool(
    "byq_backtest_cancel",
    { description: "Cancel a queued or running BYQ backtest job.", inputSchema: { job_id: z.string() } },
    byqBacktestCancel,
  );
  server.registerTool(
    "byq_factor_compute",
    {
      description: "Validate and compute a deterministic BYQ factor from point-in-time snapshots.",
      inputSchema: {
        task_id: z.string(),
        experiment_id: z.string().optional(),
        trace_id: z.string(),
        idempotency_key: z.string(),
        as_of_date: z.string(),
        factor: z.object({
          name: z.enum(["daily_return", "momentum"]),
          version: z.string(),
          lookback: z.number().int().min(1).max(252),
        }),
        securities: z.array(z.object({
          symbol: z.string(),
          exchange: z.string().optional(),
          asset_type: z.enum(["stock", "etf"]),
          list_date: z.string().nullable().optional(),
          delist_date: z.string().nullable().optional(),
        })),
        sessions: z.array(z.object({ trade_date: z.string(), is_open: z.boolean() })),
        statuses: z.array(z.object({
          symbol: z.string(),
          trade_date: z.string(),
          state: z.enum(["trading", "suspended"]),
          reason: z.string().nullable().optional(),
        })).optional(),
        bars: z.array(z.object({
          symbol: z.string(),
          trade_date: z.string(),
          open: z.number(),
          high: z.number(),
          low: z.number(),
          close: z.number(),
        })),
        universe_snapshots: z.array(z.object({ snapshot_date: z.string(), symbols: z.array(z.string()) })),
        sources: z.array(z.object({
          provider: z.string(),
          endpoint: z.string(),
          request_fingerprint: z.string(),
          dataset_id: z.string(),
          announcement_date: z.string().nullable().optional(),
          effective_date: z.string().nullable().optional(),
        })),
      },
    },
    byqFactorCompute,
  );
  server.registerTool(
    "byq_strategy_validate",
    {
      description: "Run BYQ-owned static validation and persist a StrategyDraft Artifact.",
      inputSchema: {
        task_id: z.string(),
        experiment_id: z.string().optional(),
        trace_id: z.string(),
        idempotency_key: z.string(),
        strategy: z.object({
          strategy_id: z.string(),
          name: z.string(),
          category: z.enum(["trend_following", "mean_reversion", "momentum", "volatility_based", "arbitrage", "custom"]),
          description: z.string().optional(),
          parameters: z.record(z.string(), z.unknown()).optional(),
          parameter_schema: z.record(z.string(), z.unknown()).optional(),
          source_type: z.literal("python_script").optional(),
          script: z.string(),
        }),
      },
    },
    byqStrategyValidate,
  );
  server.registerTool(
    "byq_strategy_version_create",
    {
      description: "Materialize an immutable content-addressed StrategyVersion from a validated draft.",
      inputSchema: {
        task_id: z.string(),
        experiment_id: z.string().optional(),
        draft_artifact_id: z.string(),
        trace_id: z.string(),
        idempotency_key: z.string(),
      },
    },
    byqStrategyVersionCreate,
  );
  server.registerTool(
    "byq_strategy_approve",
    {
      description: "Record an auditable approval decision separate from future execution outcome.",
      inputSchema: {
        task_id: z.string(),
        experiment_id: z.string().optional(),
        strategy_version_artifact_id: z.string(),
        reviewer_principal: z.string(),
        decision: z.enum(["approved", "rejected"]),
        rationale: z.string().optional(),
        trace_id: z.string(),
        idempotency_key: z.string(),
      },
    },
    byqStrategyApprove,
  );
  server.registerTool(
    "byq_strategy_export",
    {
      description: "Return a deterministic, secret-free StrategyVersion export.",
      inputSchema: { artifact_id: z.string() },
    },
    byqStrategyExport,
  );
  server.registerTool(
    "byq_research_task_create",
    {
      description: "Create a durable BYQ ResearchTask with idempotency and trace provenance.",
      inputSchema: {
        owner_principal: z.string(),
        title: z.string(),
        objective: z.string(),
        trace_id: z.string(),
        idempotency_key: z.string(),
      },
    },
    byqResearchTaskCreate,
  );
  server.registerTool(
    "byq_research_get",
    {
      description: "Read one BYQ ResearchTask, Experiment, or Artifact by identity.",
      inputSchema: {
        entity_type: z.enum(["research_task", "experiment", "artifact"]),
        entity_id: z.string(),
      },
    },
    byqResearchGet,
  );
  server.registerTool(
    "byq_research_transition",
    {
      description: "Apply one validated, idempotent BYQ research-domain state transition.",
      inputSchema: {
        entity_type: z.enum(["research_task", "experiment", "artifact"]),
        entity_id: z.string(),
        target_status: z.string(),
        idempotency_key: z.string(),
      },
    },
    byqResearchTransition,
  );
  server.registerTool(
    "byq_experiment_create",
    {
      description: "Create a durable Experiment with required data provenance sources.",
      inputSchema: {
        task_id: z.string(),
        name: z.string(),
        input_snapshot: z.record(z.string(), z.unknown()),
        trace_id: z.string(),
        idempotency_key: z.string(),
      },
    },
    byqExperimentCreate,
  );
  server.registerTool(
    "byq_artifact_create",
    {
      description: "Create a bounded, hashed, lineage-bearing BYQ Artifact.",
      inputSchema: {
        task_id: z.string(),
        experiment_id: z.string().optional(),
        kind: z.string(),
        content: z.record(z.string(), z.unknown()),
        lineage: z.array(z.object({ kind: z.string(), id: z.string() })),
        trace_id: z.string(),
        idempotency_key: z.string(),
      },
    },
    byqArtifactCreate,
  );
  return server;
}

const handler = toNodeHandler(createMcpHandler(buildServer));

const httpServer = createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", `http://${request.headers.host ?? "localhost"}`);

  if (request.method === "GET" && url.pathname === "/healthz") {
    writeJson(response, 200, healthPayload());
    return;
  }

  if (url.pathname !== MCP_PATH) {
    writeJson(response, 404, { service: SERVICE, status: "not_found" });
    return;
  }

  if (!authorized(request)) {
    response.setHeader("WWW-Authenticate", "Bearer");
    writeJson(response, 401, { service: SERVICE, status: "unauthorized" });
    return;
  }

  await handler(request, response);
});

httpServer.listen(PORT, "0.0.0.0", () => {
  console.log(`${SERVICE} listening on ${MCP_PATH}`);
});

async function shutdown(): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    httpServer.close((error) => (error ? reject(error) : resolve()));
  });
}

process.once("SIGTERM", () => void shutdown().then(() => process.exit(0)));
process.once("SIGINT", () => void shutdown().then(() => process.exit(0)));
