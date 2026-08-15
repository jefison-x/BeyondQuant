import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import { toNodeHandler } from "@modelcontextprotocol/node";
import { createMcpHandler, McpServer } from "@modelcontextprotocol/server";
import { z } from "zod";

import { fetchByqHealth } from "./backend-health.js";
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

async function byqMarketDaily(args: MarketDailyRequest) {
  return fetchByqMarketDaily(BACKEND_URL, args ?? {});
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
