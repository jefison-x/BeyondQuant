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
  fetchByqSignalSnapshotGet,
  type BacktestRequest,
} from "./backtest.js";
import { fetchByqFactorCompute, type FactorComputeRequest } from "./factor-research.js";
import {
  fetchByqAgentApprovalDecide,
  fetchByqAgentApprovalGet,
  fetchByqAgentApprovalRequest,
  fetchByqAgentAudit,
  fetchByqAgentAuditGet,
  fetchByqAgentAuthorize,
  fetchByqAgentRoles,
  fetchByqAgentRunStart,
  type AgentResult,
  type AgentContext,
} from "./agent.js";
import {
  fetchByqExperimentCompare,
  fetchByqLearningIterationList,
  fetchByqLearningIterationRecord,
  fetchByqLearningRunGet,
  fetchByqLearningRunReview,
  fetchByqLearningRunStart,
  fetchByqLearningSignalCreate,
  fetchByqLearningSignalGet,
  fetchByqLessonGet,
  fetchByqLessonPropose,
  fetchByqLessonReview,
} from "./learning.js";
import {
  fetchByqStrategyApprove,
  fetchByqStrategyDraftDelete,
  fetchByqStrategyDraftSave,
  fetchByqStrategyExport,
  fetchByqStrategyValidate,
  fetchByqStrategyVersionCreate,
  strategyValidationInputSchema,
  type StrategyRequest,
} from "./strategy.js";
import {
  fetchByqMarketDaily,
  fetchByqMarketFundamentals,
  fetchByqMarketValuation,
  type MarketDailyRequest,
  type MarketFundamentalsRequest,
  type MarketValuationRequest,
} from "./market-data.js";
import {
  fetchByqPoolCreate,
  fetchByqPoolGet,
  fetchByqPoolHistory,
  fetchByqPoolLifecycle,
  fetchByqPoolList,
  fetchByqPoolSnapshotReplace,
} from "./stock-pool.js";
import {
  fetchByqPaperAccount,
  fetchByqPaperAccounts,
  fetchByqPaperOrder,
  fetchByqPaperSnapshots,
} from "./paper-trading.js";
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
import { proposeWorkflowCard, workflowCardProposalSchema } from "./workflow-card.js";

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

function headerValue(headers: unknown, name: string): string | undefined {
  if (headers && typeof (headers as { get?: unknown }).get === "function") {
    const value = (headers as { get: (key: string) => string | null }).get(name);
    return value || undefined;
  }
  if (headers && typeof headers === "object") {
    const value = (headers as Record<string, unknown>)[name] ?? (headers as Record<string, unknown>)[name.toLowerCase()];
    return typeof value === "string" && value ? value : undefined;
  }
  return undefined;
}

function agentContext(extra: unknown): AgentContext {
  if (extra && typeof extra === "object" && "owner_principal" in extra) {
    const value = extra as AgentContext;
    return {
      workspace_id: value.workspace_id,
      owner_principal: value.owner_principal,
      actor_principal: value.actor_principal,
      trace_id: value.trace_id,
      session_id: value.session_id,
      dsh_run_id: value.dsh_run_id,
    };
  }
  const request = (extra as { request?: { headers?: unknown }; requestInfo?: { headers?: unknown } } | undefined);
  const headers = request?.request?.headers ?? request?.requestInfo?.headers;
  return {
    workspace_id: headerValue(headers, "x-byq-workspace-id"),
    owner_principal: headerValue(headers, "x-byq-owner-principal"),
    actor_principal: headerValue(headers, "x-byq-actor-principal"),
    trace_id: headerValue(headers, "x-byq-trace-id"),
    session_id: headerValue(headers, "x-byq-session-id"),
    dsh_run_id: headerValue(headers, "x-byq-dsh-run-id"),
  };
}

function agentContextUnavailable(): AgentResult {
  return {
    content: [{ type: "text" as const, text: JSON.stringify({ service: SERVICE, status: "error", backend: { status: "agent_context_unavailable" } }) }],
    isError: true,
  };
}

function completeAgentContext(extra: unknown): Required<AgentContext> | undefined {
  const context = agentContext(extra);
  if (!context.workspace_id || !context.owner_principal || !context.actor_principal || !context.trace_id || !context.session_id || !context.dsh_run_id) {
    return undefined;
  }
  return context as Required<AgentContext>;
}

function trustedBackendFetcher(context: Required<AgentContext>): typeof fetch {
  return (input, init) => {
    const headers = new Headers(init?.headers);
    headers.set("x-byq-workspace-id", context.workspace_id);
    headers.set("x-byq-owner-principal", context.owner_principal);
    headers.set("x-byq-actor-principal", context.actor_principal);
    headers.set("x-byq-trace-id", context.trace_id);
    headers.set("x-byq-session-id", context.session_id);
    headers.set("x-byq-dsh-run-id", context.dsh_run_id);
    return fetch(input, { ...init, headers });
  };
}

async function byqAgentContext(_args: Record<string, never>, extra: unknown) {
  const context = completeAgentContext(extra);
  if (!context) return agentContextUnavailable();
  return {
    content: [{ type: "text" as const, text: JSON.stringify({ service: SERVICE, status: "ok", context }) }],
    isError: false,
  };
}

async function byqAgentRoles() {
  return fetchByqAgentRoles(BACKEND_URL);
}

async function byqAgentRunStart(args: Record<string, unknown>, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqAgentRunStart(BACKEND_URL, args, context) : agentContextUnavailable();
}

async function byqAgentAuthorize(args: Record<string, unknown>, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqAgentAuthorize(BACKEND_URL, args, context) : agentContextUnavailable();
}

async function byqAgentAudit(args: Record<string, unknown>, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqAgentAudit(BACKEND_URL, args, context) : agentContextUnavailable();
}

async function byqAgentAuditGet(args: { run_id: string }, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqAgentAuditGet(BACKEND_URL, args.run_id, context) : agentContextUnavailable();
}

async function byqAgentApprovalRequest(args: Record<string, unknown>, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqAgentApprovalRequest(BACKEND_URL, args, context) : agentContextUnavailable();
}

async function byqAgentApprovalGet(args: { approval_id: string }, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqAgentApprovalGet(BACKEND_URL, args.approval_id, context) : agentContextUnavailable();
}

async function byqAgentApprovalDecide(args: { approval_id: string; decision: string; rationale?: string }, extra: unknown) {
  const context = completeAgentContext(extra);
  if (!context) return agentContextUnavailable();
  const { approval_id, ...request } = args;
  return fetchByqAgentApprovalDecide(BACKEND_URL, approval_id, request, context);
}

async function byqLearningRunStart(args: Record<string, unknown>, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqLearningRunStart(BACKEND_URL, args, context) : agentContextUnavailable();
}

async function byqLearningRunGet(args: { run_id: string }, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqLearningRunGet(BACKEND_URL, args.run_id, context) : agentContextUnavailable();
}

async function byqLearningIterationRecord(args: { run_id: string } & Record<string, unknown>, extra: unknown) {
  const context = completeAgentContext(extra);
  if (!context) return agentContextUnavailable();
  const { run_id, ...request } = args;
  return fetchByqLearningIterationRecord(BACKEND_URL, run_id, request, context);
}

async function byqLearningIterationList(args: { run_id: string }, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqLearningIterationList(BACKEND_URL, args.run_id, context) : agentContextUnavailable();
}

async function byqLearningRunReview(args: { run_id: string; decision: string; rationale?: string }, extra: unknown) {
  const context = completeAgentContext(extra);
  if (!context) return agentContextUnavailable();
  const { run_id, ...request } = args;
  return fetchByqLearningRunReview(BACKEND_URL, run_id, request, context);
}

async function byqLearningSignalCreate(args: Record<string, unknown>, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqLearningSignalCreate(BACKEND_URL, args, context) : agentContextUnavailable();
}

async function byqLearningSignalGet(args: { signal_id: string }, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqLearningSignalGet(BACKEND_URL, args.signal_id, context) : agentContextUnavailable();
}

async function byqExperimentCompare(args: Record<string, unknown>, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqExperimentCompare(BACKEND_URL, args, context) : agentContextUnavailable();
}

async function byqLessonPropose(args: Record<string, unknown>, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqLessonPropose(BACKEND_URL, args, context) : agentContextUnavailable();
}

async function byqLessonGet(args: { lesson_id: string }, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqLessonGet(BACKEND_URL, args.lesson_id, context) : agentContextUnavailable();
}

async function byqLessonReview(args: { lesson_id: string; decision: string; rationale?: string }, extra: unknown) {
  const context = completeAgentContext(extra);
  if (!context) return agentContextUnavailable();
  const { lesson_id, ...request } = args;
  return fetchByqLessonReview(BACKEND_URL, lesson_id, request, context);
}

async function byqBacktestSubmit(args: BacktestRequest, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqBacktestSubmit(BACKEND_URL, args ?? {}, trustedBackendFetcher(context)) : agentContextUnavailable();
}

async function byqBacktestGet(args: { job_id: string }, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqBacktestGet(BACKEND_URL, args.job_id, trustedBackendFetcher(context)) : agentContextUnavailable();
}

async function byqBacktestRun(args: { job_id: string }, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqBacktestRun(BACKEND_URL, args.job_id, trustedBackendFetcher(context)) : agentContextUnavailable();
}

async function byqBacktestCancel(args: { job_id: string }, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqBacktestCancel(BACKEND_URL, args.job_id, trustedBackendFetcher(context)) : agentContextUnavailable();
}

async function byqMarketDaily(args: MarketDailyRequest, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqMarketDaily(BACKEND_URL, args ?? {}, trustedBackendFetcher(context)) : agentContextUnavailable();
}

async function byqMarketValuation(args: MarketValuationRequest, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqMarketValuation(BACKEND_URL, args, trustedBackendFetcher(context)) : agentContextUnavailable();
}

async function byqMarketFundamentals(args: MarketFundamentalsRequest, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqMarketFundamentals(BACKEND_URL, args, trustedBackendFetcher(context)) : agentContextUnavailable();
}

async function byqFactorCompute(args: FactorComputeRequest, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqFactorCompute(BACKEND_URL, args ?? {}, trustedBackendFetcher(context)) : agentContextUnavailable();
}

async function byqStrategyDraftSave(args: StrategyRequest, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqStrategyDraftSave(BACKEND_URL, args, trustedBackendFetcher(context)) : agentContextUnavailable();
}

async function byqStrategyDraftDelete(args: { artifact_id: string }, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqStrategyDraftDelete(BACKEND_URL, args.artifact_id, trustedBackendFetcher(context)) : agentContextUnavailable();
}

async function byqStrategyValidate(args: StrategyRequest, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqStrategyValidate(BACKEND_URL, args ?? {}, trustedBackendFetcher(context)) : agentContextUnavailable();
}

async function byqStrategyVersionCreate(args: StrategyRequest, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqStrategyVersionCreate(BACKEND_URL, args ?? {}, trustedBackendFetcher(context)) : agentContextUnavailable();
}

async function byqStrategyApprove(args: StrategyRequest, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqStrategyApprove(BACKEND_URL, args ?? {}, trustedBackendFetcher(context)) : agentContextUnavailable();
}

async function byqStrategyExport(args: { artifact_id: string }, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqStrategyExport(BACKEND_URL, args.artifact_id, trustedBackendFetcher(context)) : agentContextUnavailable();
}

async function byqResearchTaskCreate(args: ResearchTaskCreateRequest, extra: unknown) {
  const context = completeAgentContext(extra);
  if (!context) return agentContextUnavailable();
  return fetchByqResearchTaskCreate(BACKEND_URL, {
    ...args,
    owner_principal: context.owner_principal,
    trace_id: context.trace_id,
  }, trustedBackendFetcher(context));
}

async function byqResearchGet(args: { entity_type: ResearchEntityType; entity_id: string }, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqResearchGet(BACKEND_URL, args.entity_type, args.entity_id, trustedBackendFetcher(context)) : agentContextUnavailable();
}

async function byqSignalSnapshotGet(args: { artifact_id: string }, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqSignalSnapshotGet(BACKEND_URL, args.artifact_id, trustedBackendFetcher(context)) : agentContextUnavailable();
}

async function byqResearchTransition(args: ResearchTransitionRequest, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqResearchTransition(BACKEND_URL, args, trustedBackendFetcher(context)) : agentContextUnavailable();
}

async function byqExperimentCreate(args: ExperimentCreateRequest, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqExperimentCreate(BACKEND_URL, args, trustedBackendFetcher(context)) : agentContextUnavailable();
}

async function byqArtifactCreate(args: ArtifactCreateRequest, extra: unknown) {
  const context = completeAgentContext(extra);
  return context ? fetchByqArtifactCreate(BACKEND_URL, args, trustedBackendFetcher(context)) : agentContextUnavailable();
}

function buildServer(factoryContext: unknown = undefined): McpServer {
  const trustedContext = agentContext(factoryContext);
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
    "byq_workflow_card_propose",
    {
      description: "Propose one bounded BYQ strategy, stock-candidate, or optimization presentation card. This never mutates Domain state or grants approval.",
      inputSchema: workflowCardProposalSchema,
    },
    proposeWorkflowCard,
  );
  const poolContext = () => completeAgentContext(trustedContext);
  server.registerTool(
    "byq_pool_list",
    { description: "List owner-scoped BYQ Stock Pools.", inputSchema: {} },
    () => { const context = poolContext(); return context ? fetchByqPoolList(BACKEND_URL, context) : agentContextUnavailable(); },
  );
  server.registerTool(
    "byq_pool_get",
    { description: "Read one owner-scoped BYQ Stock Pool and its current immutable snapshot.", inputSchema: { pool_id: z.string() } },
    (args) => { const context = poolContext(); return context ? fetchByqPoolGet(BACKEND_URL, args.pool_id, context) : agentContextUnavailable(); },
  );
  server.registerTool(
    "byq_pool_create",
    { description: "Create an owner-scoped custom Stock Pool and first immutable snapshot.", inputSchema: {
      name: z.string(), description: z.string().optional(), symbols: z.array(z.string()).min(1),
      weights: z.record(z.string(), z.union([z.string(), z.number()])).optional(),
      definition: z.record(z.string(), z.unknown()).optional(),
    } },
    (args) => { const context = poolContext(); return context ? fetchByqPoolCreate(BACKEND_URL, { ...args, pool_type: "custom" }, context) : agentContextUnavailable(); },
  );
  server.registerTool(
    "byq_pool_snapshot_replace",
    { description: "Append or idempotently reuse a complete custom-pool membership snapshot.", inputSchema: {
      pool_id: z.string(), expected_current_snapshot_id: z.string(), idempotency_key: z.string(),
      symbols: z.array(z.string()).min(1), weights: z.record(z.string(), z.union([z.string(), z.number()])).optional(),
      definition: z.record(z.string(), z.unknown()).optional(),
    } },
    (args) => { const context = poolContext(); const { pool_id, ...body } = args; return context ? fetchByqPoolSnapshotReplace(BACKEND_URL, pool_id, body, context) : agentContextUnavailable(); },
  );
  server.registerTool(
    "byq_pool_history",
    { description: "List immutable snapshot history for one owner-scoped Stock Pool.", inputSchema: { pool_id: z.string() } },
    (args) => { const context = poolContext(); return context ? fetchByqPoolHistory(BACKEND_URL, args.pool_id, context) : agentContextUnavailable(); },
  );
  server.registerTool(
    "byq_pool_lifecycle",
    { description: "Activate, deactivate, or tombstone-delete an owner-scoped Stock Pool.", inputSchema: {
      pool_id: z.string(), status: z.enum(["active", "inactive", "deleted"]), reason: z.string(), idempotency_key: z.string(),
    } },
    (args) => { const context = poolContext(); const { pool_id, ...body } = args; return context ? fetchByqPoolLifecycle(BACKEND_URL, pool_id, body, context) : agentContextUnavailable(); },
  );
  server.registerTool(
    "byq_paper_account_list",
    { description: "List owner-scoped BYQ simulation-only Paper Trading accounts.", inputSchema: {} },
    () => { const context = poolContext(); return context ? fetchByqPaperAccounts(BACKEND_URL, context) : agentContextUnavailable(); },
  );
  server.registerTool(
    "byq_paper_account_get",
    { description: "Read one owner-scoped Paper Trading account projection.", inputSchema: { account_id: z.string() } },
    (args) => { const context = poolContext(); return context ? fetchByqPaperAccount(BACKEND_URL, args.account_id, context) : agentContextUnavailable(); },
  );
  server.registerTool(
    "byq_paper_order_get",
    { description: "Read one persisted owner-scoped paper order audit projection.", inputSchema: { account_id: z.string(), order_id: z.string() } },
    (args) => { const context = poolContext(); return context ? fetchByqPaperOrder(BACKEND_URL, args.account_id, args.order_id, context) : agentContextUnavailable(); },
  );
  server.registerTool(
    "byq_paper_snapshot_list",
    { description: "List immutable settlement snapshots for one owner-scoped paper account.", inputSchema: { account_id: z.string() } },
    (args) => { const context = poolContext(); return context ? fetchByqPaperSnapshots(BACKEND_URL, args.account_id, context) : agentContextUnavailable(); },
  );
  server.registerTool(
    "byq_agent_context",
    {
      description: "Return the trusted BYQ owner, actor, trace, and DSH session context for this agent run.",
      inputSchema: {},
    },
    () => byqAgentContext({}, trustedContext),
  );
  server.registerTool(
    "byq_agent_roles",
    {
      description: "List the versioned BYQ quant research role catalogue and capability policy.",
      inputSchema: {},
    },
    byqAgentRoles,
  );
  server.registerTool(
    "byq_agent_run_start",
    {
      description: "Start an owner-scoped BYQ agent run correlated to the trusted DSH session and trace.",
      inputSchema: {
        role_id: z.enum(["quant_orchestrator", "market_researcher", "factor_researcher", "strategy_researcher", "backtest_analyst"]),
        parent_run_id: z.string().optional(),
        idempotency_key: z.string(),
      },
    },
    (args) => byqAgentRunStart(args, trustedContext),
  );
  server.registerTool(
    "byq_agent_authorize",
    {
      description: "Ask BYQ whether the active role may invoke a domain action; approval-required actions never auto-authorize.",
      inputSchema: {
        run_id: z.string(),
        action: z.string(),
        resource_type: z.string().optional(),
        resource_id: z.string().optional(),
      },
    },
    (args) => byqAgentAuthorize(args, trustedContext),
  );
  server.registerTool(
    "byq_agent_audit",
    {
      description: "Append a bounded, owner-scoped audit outcome for a BYQ domain action.",
      inputSchema: {
        run_id: z.string(),
        action: z.string(),
        outcome: z.string(),
        resource_type: z.string().optional(),
        resource_id: z.string().optional(),
        detail: z.record(z.string(), z.unknown()).optional(),
      },
    },
    (args) => byqAgentAudit(args, trustedContext),
  );
  server.registerTool(
    "byq_agent_audit_get",
    {
      description: "Read the owner-scoped audit view for one BYQ agent run.",
      inputSchema: { run_id: z.string() },
    },
    (args) => byqAgentAuditGet(args, trustedContext),
  );
  server.registerTool(
    "byq_agent_approval_request",
    {
      description: "Create a pending BYQ human approval for a consequential agent action.",
      inputSchema: {
        run_id: z.string(),
        action: z.string(),
        reason: z.string(),
        idempotency_key: z.string(),
      },
    },
    (args) => byqAgentApprovalRequest(args, trustedContext),
  );
  server.registerTool(
    "byq_agent_approval_get",
    {
      description: "Read one owner-scoped BYQ agent approval and its separate execution outcome.",
      inputSchema: { approval_id: z.string() },
    },
    (args) => byqAgentApprovalGet(args, trustedContext),
  );
  server.registerTool(
    "byq_agent_approval_decide",
    {
      description: "Record a trusted human approval decision; the initiating agent cannot self-approve.",
      inputSchema: {
        approval_id: z.string(),
        decision: z.enum(["approved", "rejected"]),
        rationale: z.string().optional(),
      },
    },
    (args) => byqAgentApprovalDecide(args, trustedContext),
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
    (args) => byqMarketDaily(args, trustedContext),
  );
  server.registerTool(
    "byq_market_valuation",
    {
      description: "Read exact-session BYQ valuation fields from durable data with explicit completeness evidence. This tool never calls a provider or fills missing values.",
      inputSchema: {
        symbols: z.array(z.string().regex(/^(?:[03]\d{5}\.SZ|6\d{5}\.SH)$/)).min(1).max(20),
        trade_date: z.string().regex(/^\d{8}$/).describe("Exact YYYYMMDD trade date."),
        fields: z.array(z.enum([
          "turnover_rate", "turnover_rate_f", "volume_ratio", "pe", "pe_ttm", "pb",
          "ps", "ps_ttm", "dv_ratio", "dv_ttm", "total_share", "float_share",
          "free_share", "total_mv", "circ_mv",
        ])).min(1).max(12),
      },
    },
    (args) => byqMarketValuation(args, trustedContext),
  );
  server.registerTool(
    "byq_market_fundamentals",
    {
      description: "Read the latest BYQ financial report visible after its conservative next-day announcement boundary. This tool never calls a provider or fills missing values.",
      inputSchema: {
        symbols: z.array(z.string().regex(/^(?:[03]\d{5}\.SZ|6\d{5}\.SH)$/)).min(1).max(20),
        as_of_date: z.string().regex(/^\d{8}$/).describe("Point-in-time YYYYMMDD research date."),
        fields: z.array(z.enum([
          "eps", "roe", "roa", "grossprofit_margin", "debt_to_assets", "or_yoy", "netprofit_yoy",
        ])).min(1).max(12),
      },
    },
    (args) => byqMarketFundamentals(args, trustedContext),
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
    (args) => byqBacktestSubmit(args, trustedContext),
  );
  server.registerTool(
    "byq_backtest_get",
    { description: "Read durable BYQ backtest job state and immutable result reference.", inputSchema: { job_id: z.string() } },
    (args) => byqBacktestGet(args, trustedContext),
  );
  server.registerTool(
    "byq_signal_snapshot_get",
    {
      description: "Read an immutable, validated BYQ signal_snapshot artifact (frozen backtest input, ADR-0017). Read-only.",
      inputSchema: { artifact_id: z.string() },
    },
    (args) => byqSignalSnapshotGet(args, trustedContext),
  );
  server.registerTool(
    "byq_backtest_run",
    { description: "Run one queued deterministic BYQ backtest job through the worker boundary.", inputSchema: { job_id: z.string() } },
    (args) => byqBacktestRun(args, trustedContext),
  );
  server.registerTool(
    "byq_backtest_cancel",
    { description: "Cancel a queued or running BYQ backtest job.", inputSchema: { job_id: z.string() } },
    (args) => byqBacktestCancel(args, trustedContext),
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
    (args) => byqFactorCompute(args, trustedContext),
  );
  server.registerTool(
    "byq_strategy_draft_save",
    {
      description: "Durably save a strategy draft (Phase 33); tolerates intermediate edits that do not yet pass static validation.",
      inputSchema: {
        task_id: z.string(),
        experiment_id: z.string().optional(),
        trace_id: z.string(),
        idempotency_key: z.string(),
        strategy: z.record(z.string(), z.unknown()),
      },
    },
    (args) => byqStrategyDraftSave(args, trustedContext),
  );
  server.registerTool(
    "byq_strategy_draft_delete",
    {
      description: "Delete (soft-supersede) an owner-scoped strategy draft (Phase 33).",
      inputSchema: { artifact_id: z.string() },
    },
    (args) => byqStrategyDraftDelete(args, trustedContext),
  );
  server.registerTool(
    "byq_strategy_validate",
    {
      description: "Validate and persist a StrategyDraft. script must define class CustomStrategy with exactly one synchronous generate_signals(self, data, parameters) or generate_target_weights(self, data, portfolio_state, parameters). A planned research task is valid. On 422, use the safe validation message for at most one repair.",
      inputSchema: strategyValidationInputSchema,
    },
    (args) => byqStrategyValidate(args, trustedContext),
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
    (args) => byqStrategyVersionCreate(args, trustedContext),
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
    (args) => byqStrategyApprove(args, trustedContext),
  );
  server.registerTool(
    "byq_strategy_export",
    {
      description: "Return a deterministic, secret-free StrategyVersion export.",
      inputSchema: { artifact_id: z.string() },
    },
    (args) => byqStrategyExport(args, trustedContext),
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
    (args) => byqResearchTaskCreate(args, trustedContext),
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
    (args) => byqResearchGet(args, trustedContext),
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
    (args) => byqResearchTransition(args, trustedContext),
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
    (args) => byqExperimentCreate(args, trustedContext),
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
    (args) => byqArtifactCreate(args, trustedContext),
  );
  server.registerTool(
    "byq_learning_run_start",
    {
      description: "Start a bounded, owner-scoped BYQ learning run with explicit budgets and stopping rules.",
      inputSchema: {
        task_id: z.string(),
        budget: z.object({
          max_iterations: z.number().int().min(1).max(100),
          max_repairs: z.number().int().min(0).max(10),
        }),
        stopping_rules: z.object({
          target_metric: z.string(),
          target_value: z.number(),
          operator: z.enum(["gte", "lte"]),
        }).optional(),
        lineage: z.array(z.object({ kind: z.string(), id: z.string() })).optional(),
        idempotency_key: z.string(),
      },
    },
    (args) => byqLearningRunStart(args, trustedContext),
  );
  server.registerTool(
    "byq_learning_run_get",
    {
      description: "Read one owner-scoped BYQ learning run and its bounded state.",
      inputSchema: { run_id: z.string() },
    },
    (args) => byqLearningRunGet(args, trustedContext),
  );
  server.registerTool(
    "byq_learning_iteration_record",
    {
      description: "Append one ordered, idempotent learning iteration to an active bounded run.",
      inputSchema: {
        run_id: z.string(),
        iteration_index: z.number().int().positive(),
        attempt: z.number().int().positive(),
        outcome: z.enum(["produced", "no_change", "failed"]),
        feedback: z.record(z.string(), z.unknown()).optional(),
        source_refs: z.array(z.object({ kind: z.string(), id: z.string() })).optional(),
        result_refs: z.array(z.object({ kind: z.string(), id: z.string() })).optional(),
        idempotency_key: z.string(),
      },
    },
    (args) => byqLearningIterationRecord(args, trustedContext),
  );
  server.registerTool(
    "byq_learning_iteration_list",
    {
      description: "Read the ordered, replayable iteration history of one BYQ learning run.",
      inputSchema: { run_id: z.string() },
    },
    (args) => byqLearningIterationList(args, trustedContext),
  );
  server.registerTool(
    "byq_learning_run_review",
    {
      description: "Record a trusted human review that approves or rejects an awaiting learning run.",
      inputSchema: {
        run_id: z.string(),
        decision: z.enum(["approved", "rejected"]),
        rationale: z.string().optional(),
      },
    },
    (args) => byqLearningRunReview(args, trustedContext),
  );
  server.registerTool(
    "byq_evaluation_signal_create",
    {
      description: "Create a finite, artifact-backed BYQ evaluation signal for a metric.",
      inputSchema: {
        task_id: z.string(),
        experiment_id: z.string().optional(),
        source_artifact_id: z.string(),
        metric: z.string(),
        value: z.number(),
        unit: z.string().optional(),
        lineage: z.array(z.object({ kind: z.string(), id: z.string() })).optional(),
        idempotency_key: z.string(),
      },
    },
    (args) => byqLearningSignalCreate(args, trustedContext),
  );
  server.registerTool(
    "byq_evaluation_signal_get",
    {
      description: "Read one owner-scoped BYQ evaluation signal.",
      inputSchema: { signal_id: z.string() },
    },
    (args) => byqLearningSignalGet(args, trustedContext),
  );
  server.registerTool(
    "byq_experiment_compare",
    {
      description: "Compare two experiments' deterministic evaluation signals for one metric.",
      inputSchema: {
        task_id: z.string(),
        experiment_a_id: z.string(),
        experiment_b_id: z.string(),
        metric: z.string(),
      },
    },
    (args) => byqExperimentCompare(args, trustedContext),
  );
  server.registerTool(
    "byq_lesson_propose",
    {
      description: "Propose a bounded BYQ lesson from validated artifact or evaluation-signal evidence.",
      inputSchema: {
        task_id: z.string(),
        content: z.record(z.string(), z.unknown()),
        evidence: z.array(z.object({ kind: z.enum(["artifact", "evaluation_signal"]), id: z.string() })).min(1),
        validation: z.record(z.string(), z.unknown()).optional(),
        idempotency_key: z.string(),
      },
    },
    (args) => byqLessonPropose(args, trustedContext),
  );
  server.registerTool(
    "byq_lesson_get",
    {
      description: "Read one owner-scoped BYQ lesson and its promotion history.",
      inputSchema: { lesson_id: z.string() },
    },
    (args) => byqLessonGet(args, trustedContext),
  );
  server.registerTool(
    "byq_lesson_review",
    {
      description: "Record a trusted human promotion decision for a proposed lesson.",
      inputSchema: {
        lesson_id: z.string(),
        decision: z.enum(["approved", "rejected", "superseded"]),
        rationale: z.string().optional(),
      },
    },
    (args) => byqLessonReview(args, trustedContext),
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
