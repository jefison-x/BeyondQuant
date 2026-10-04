import { randomBytes } from "node:crypto";
import { setTimeout as delay } from "node:timers/promises";
import type { AcpAgentClaims } from "./acp-auth.js";

const BACKEND_TIMEOUT_MS = 8000;
const RUN_ID = /^agent_run_[0-9a-f]{32}$/;
const ROOT_ID = /^[0-9a-f]{32}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const MCP_REQUEST_ID = /^[0-9a-f]{32}$/;
const BOOTSTRAP_INGRESS_TOOLS = new Set(["byq_health", "byq_agent_roles", "byq_agent_context"]);
const ROOT_REGISTRATION_RETRY_DELAYS_MS = [100, 250, 500] as const;
const ROOT_NOT_REGISTERED_DETAIL = "ACP root is not yet registered by Backend";

export type AcpAgentBindReceipt = {
  schema_version: "byq-acp-agent-bind-receipt.v1";
  root_run_id: string;
  runtime_boot_id: string;
  native_agent_session_id: string;
  native_parent_session_id: string | null;
  agent_run_id: string;
  parent_run_id: string | null;
  origin: "root" | "subagent";
  depth: number;
  status: "bound";
  binding_sha256: string;
};

export type AcpDomainObservationReceipt = {
  schema_version: "byq-acp-domain-call-observation-receipt.v1";
  mcp_request_id: string;
  root_run_id: string;
  sequence: number;
  event_sha256: string;
};

export type AcpToolIngressReceipt = {
  schema_version: "byq-acp-tool-ingress-receipt.v1";
  mcp_request_id: string;
  root_run_id: string;
  runtime_boot_id: string;
  native_root_session_id: string;
  native_agent_session_id: string;
  native_parent_session_id: string | null;
  origin: "root" | "subagent";
  depth: number;
  tool_name: string;
  agent_run_id: string | null;
  sequence: number;
  event_sha256: string;
};

export type AcpToolIngressOutcome = "settled" | "unknown";

export type AcpToolIngressAbortReceipt = {
  schema_version: "byq-acp-tool-ingress-abort-receipt.v1";
  mcp_request_id: string;
  root_run_id: string;
  runtime_boot_id: string;
  native_root_session_id: string;
  native_agent_session_id: string;
  native_parent_session_id: string | null;
  origin: "root" | "subagent";
  depth: number;
  tool_name: string;
  arguments_sha256: string;
  sequence: number;
  event_sha256: string;
  outcome: "aborted_before_dispatch";
  abort_sha256: string;
};

export type AcpToolIngressSettlementReceipt = {
  schema_version: "byq-acp-tool-ingress-settle-receipt.v1";
  mcp_request_id: string;
  root_run_id: string;
  runtime_boot_id: string;
  native_agent_session_id: string;
  tool_name: string;
  sequence: number;
  event_sha256: string;
  outcome: AcpToolIngressOutcome;
  settlement_sha256: string;
};

export type AcpAgentBindingStatus =
  | { schema_version: "byq-acp-agent-binding-status.v1"; root_run_id: string;
      runtime_boot_id: string; native_agent_session_id: string; status: "pending" }
  | { schema_version: "byq-acp-agent-binding-status.v1"; root_run_id: string;
      runtime_boot_id: string; native_agent_session_id: string; status: "bound";
      receipt: AcpAgentBindReceipt };

export type Fetcher = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const keys = Object.keys(value).sort();
  const sorted = [...expected].sort();
  return keys.length === sorted.length && keys.every((key, index) => key === sorted[index]);
}

function scopeHeaders(claims: AcpAgentClaims, proofToken: string): Headers {
  const headers = new Headers({
    authorization: `Bearer ${proofToken}`,
    "content-type": "application/json",
    "x-byq-owner-principal": claims.owner_principal,
    "x-byq-workspace-id": claims.workspace_id,
    "x-byq-actor-principal": claims.actor_principal,
    "x-byq-trace-id": claims.trace_id,
    "x-byq-session-id": claims.session_id,
    "x-byq-dsh-run-id": claims.dsh_run_id,
    "x-byq-runtime-boot-id": claims.runtime_boot_id,
    "x-byq-root-run-id": claims.root_run_id,
  });
  return headers;
}

function nativeHeaders(claims: AcpAgentClaims, headers: Headers): void {
  headers.set("x-byq-acp-native-agent-session-id", claims.native_agent_session_id);
  headers.set("x-byq-acp-native-root-session-id", claims.native_root_session_id);
  headers.set("x-byq-acp-native-parent-session-id", claims.native_parent_session_id ?? "");
  headers.set("x-byq-acp-origin", claims.origin);
  headers.set("x-byq-acp-depth", String(claims.depth));
}

function isValidParentRunId(value: unknown, claims: AcpAgentClaims): value is string | null {
  if (claims.origin === "root") return value === null || value === undefined;
  return typeof value === "string" && RUN_ID.test(value);
}

function validBindReceipt(value: unknown, claims: AcpAgentClaims, agentRunId: string,
  parentRunId: string | null): value is AcpAgentBindReceipt {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const receipt = value as Record<string, unknown>;
  return hasExactKeys(receipt, ["schema_version", "root_run_id", "runtime_boot_id", "native_agent_session_id",
    "native_parent_session_id", "agent_run_id", "parent_run_id", "origin", "depth", "status", "binding_sha256"])
    && receipt.schema_version === "byq-acp-agent-bind-receipt.v1"
    && receipt.root_run_id === claims.root_run_id
    && receipt.runtime_boot_id === claims.runtime_boot_id
    && receipt.native_agent_session_id === claims.native_agent_session_id
    && receipt.native_parent_session_id === claims.native_parent_session_id
    && receipt.agent_run_id === agentRunId
    && receipt.parent_run_id === parentRunId
    && receipt.origin === claims.origin && receipt.depth === claims.depth
    && receipt.status === "bound"
    && typeof receipt.binding_sha256 === "string" && SHA256.test(receipt.binding_sha256);
}

function validObservationReceipt(value: unknown, claims: AcpAgentClaims,
  requestId: string): value is AcpDomainObservationReceipt {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const receipt = value as Record<string, unknown>;
  return hasExactKeys(receipt, ["schema_version", "mcp_request_id", "root_run_id", "sequence", "event_sha256"])
    && receipt.schema_version === "byq-acp-domain-call-observation-receipt.v1"
    && receipt.mcp_request_id === requestId && MCP_REQUEST_ID.test(String(receipt.mcp_request_id))
    && receipt.root_run_id === claims.root_run_id && ROOT_ID.test(String(receipt.root_run_id))
    && Number.isSafeInteger(receipt.sequence) && (receipt.sequence as number) > 0
    && typeof receipt.event_sha256 === "string" && SHA256.test(receipt.event_sha256);
}

function validToolIngressReceipt(value: unknown, claims: AcpAgentClaims, requestId: string,
  toolName: string, allowUnboundAgent: boolean): value is AcpToolIngressReceipt {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const receipt = value as Record<string, unknown>;
  const runIdValid = receipt.agent_run_id === null
    ? allowUnboundAgent
    : typeof receipt.agent_run_id === "string" && RUN_ID.test(receipt.agent_run_id);
  return hasExactKeys(receipt, ["schema_version", "mcp_request_id", "root_run_id", "runtime_boot_id",
    "native_root_session_id", "native_agent_session_id", "native_parent_session_id", "origin", "depth",
    "tool_name", "agent_run_id", "sequence", "event_sha256"])
    && receipt.schema_version === "byq-acp-tool-ingress-receipt.v1"
    && receipt.mcp_request_id === requestId && MCP_REQUEST_ID.test(String(receipt.mcp_request_id))
    && receipt.root_run_id === claims.root_run_id && ROOT_ID.test(String(receipt.root_run_id))
    && receipt.runtime_boot_id === claims.runtime_boot_id
    && receipt.native_root_session_id === claims.native_root_session_id
    && receipt.native_agent_session_id === claims.native_agent_session_id
    && receipt.native_parent_session_id === claims.native_parent_session_id
    && receipt.origin === claims.origin && receipt.depth === claims.depth
    && runIdValid && receipt.tool_name === toolName
    && Number.isSafeInteger(receipt.sequence) && (receipt.sequence as number) > 0
    && typeof receipt.event_sha256 === "string" && SHA256.test(receipt.event_sha256);
}

async function jsonObject(response: Response): Promise<Record<string, unknown> | undefined> {
  if (!response.ok) { await response.body?.cancel(); return undefined; }
  try {
    const value = await response.json();
    return value && typeof value === "object" && !Array.isArray(value)
      ? value as Record<string, unknown> : undefined;
  } catch {
    return undefined;
  }
}

/** Add the dedicated MCP proof and signed native lineage only to AgentRun registration calls. */
export function acpAgentRunRegistrationFetcher(
  claims: AcpAgentClaims,
  proofToken: string,
  fetcher: Fetcher,
): Fetcher {
  return async (input, init) => {
    const url = new URL(typeof input === "string" || input instanceof URL ? input : input.url);
    const isCreate = url.pathname === "/v1/agents/runs" && (init?.method ?? "GET").toUpperCase() === "POST";
    const isRegistration = isCreate || url.pathname === "/v1/agents/runs/registration-receipt";
    if (!isRegistration) return fetcher(input, init);
    const headers = scopeHeaders(claims, proofToken);
    new Headers(init?.headers).forEach((value, key) => headers.set(key, value));
    // Identity claims and the service credential are authoritative; no caller
    // header may replace them after request construction.
    headers.set("authorization", `Bearer ${proofToken}`);
    headers.set("x-byq-owner-principal", claims.owner_principal);
    headers.set("x-byq-workspace-id", claims.workspace_id);
    headers.set("x-byq-actor-principal", claims.actor_principal);
    headers.set("x-byq-trace-id", claims.trace_id);
    headers.set("x-byq-session-id", claims.session_id);
    headers.set("x-byq-dsh-run-id", claims.dsh_run_id);
    headers.set("x-byq-runtime-boot-id", claims.runtime_boot_id);
    headers.set("x-byq-root-run-id", claims.root_run_id);
    nativeHeaders(claims, headers);
    const trustedInit = { ...init, headers };
    if (!isCreate || claims.origin !== "root" || typeof init?.body !== "string") {
      return fetcher(input, trustedInit);
    }
    let hasOriginalKey = false;
    try {
      const body = JSON.parse(init.body) as Record<string, unknown>;
      const key = body?.idempotency_key;
      hasOriginalKey = typeof key === "string" && key.length > 0 && key.length <= 128
        && key === key.trim() && !/[\u0000-\u001f\u007f]/.test(key);
    } catch { /* malformed registration bodies are sent once and rejected by Backend */ }
    const maximumRetries = hasOriginalKey ? ROOT_REGISTRATION_RETRY_DELAYS_MS.length : 0;
    for (let attempt = 0; ; attempt += 1) {
      const response = await fetcher(input, trustedInit);
      if (attempt >= maximumRetries || response.status !== 409) return response;
      let rootIsNotRegistered = false;
      try {
        const payload = await response.clone().json() as Record<string, unknown>;
        rootIsNotRegistered = payload?.detail === ROOT_NOT_REGISTERED_DETAIL;
      } catch { /* only the exact documented pre-effect conflict is retryable */ }
      if (!rootIsNotRegistered) return response;
      await delay(ROOT_REGISTRATION_RETRY_DELAYS_MS[attempt]);
    }
  };
}

/** Submit one validated MCP tool request. There is deliberately no retry. */
export async function observeAcpDomainCall(
  backendUrl: string,
  proofToken: string,
  claims: AcpAgentClaims,
  action: string,
  args: Record<string, unknown>,
  fetcher: Fetcher = fetch,
): Promise<AcpDomainObservationReceipt | undefined> {
  const mcpRequestId = randomBytes(16).toString("hex");
  const headers = scopeHeaders(claims, proofToken);
  const body = {
    schema_version: "byq-acp-domain-call-observe.v1",
    mcp_request_id: mcpRequestId,
    root_run_id: claims.root_run_id,
    runtime_boot_id: claims.runtime_boot_id,
    native_agent_session_id: claims.native_agent_session_id,
    action,
    arguments: args,
  };
  try {
    const response = await fetcher(`${backendUrl}/internal/acp/domain-call-observe`, {
      method: "POST", headers, body: JSON.stringify(body), signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
    const payload = await jsonObject(response);
    return payload && validObservationReceipt(payload, claims, mcpRequestId)
      ? payload as AcpDomainObservationReceipt : undefined;
  } catch {
    return undefined;
  }
}

/** Submit every Backend-facing Product MCP call before it reaches its handler. No retry on unknown outcome. */
export async function observeAcpToolIngress(
  backendUrl: string,
  proofToken: string,
  claims: AcpAgentClaims,
  toolName: string,
  args: Record<string, unknown>,
  fetcher: Fetcher = fetch,
  mcpRequestId: string = randomBytes(16).toString("hex"),
): Promise<AcpToolIngressReceipt | undefined> {
  if (!MCP_REQUEST_ID.test(mcpRequestId)) return undefined;
  const headers = scopeHeaders(claims, proofToken);
  const body = {
    schema_version: "byq-acp-tool-ingress-observe.v1",
    mcp_request_id: mcpRequestId,
    root_run_id: claims.root_run_id,
    runtime_boot_id: claims.runtime_boot_id,
    native_root_session_id: claims.native_root_session_id,
    native_agent_session_id: claims.native_agent_session_id,
    native_parent_session_id: claims.native_parent_session_id,
    origin: claims.origin,
    depth: claims.depth,
    tool_name: toolName,
    arguments: args,
  };
  const bootstrapTool = BOOTSTRAP_INGRESS_TOOLS.has(toolName);
  try {
    const response = await fetcher(`${backendUrl}/internal/acp/tool-ingress-observe`, {
      method: "POST", headers, body: JSON.stringify(body), signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
    const payload = await jsonObject(response);
    return payload && validToolIngressReceipt(payload, claims, mcpRequestId, toolName, bootstrapTool)
      ? payload as AcpToolIngressReceipt : undefined;
  } catch {
    return undefined;
  }
}

/** This may only be called after observe yielded no valid receipt and before handler entry. */
export async function abortAcpToolIngressBeforeDispatch(
  backendUrl: string,
  proofToken: string,
  claims: AcpAgentClaims,
  toolName: string,
  args: Record<string, unknown>,
  mcpRequestId: string,
  fetcher: Fetcher = fetch,
): Promise<AcpToolIngressAbortReceipt | undefined> {
  if (!MCP_REQUEST_ID.test(mcpRequestId)) return undefined;
  const body = {
    schema_version: "byq-acp-tool-ingress-abort.v1",
    mcp_request_id: mcpRequestId,
    root_run_id: claims.root_run_id,
    runtime_boot_id: claims.runtime_boot_id,
    native_root_session_id: claims.native_root_session_id,
    native_agent_session_id: claims.native_agent_session_id,
    native_parent_session_id: claims.native_parent_session_id,
    origin: claims.origin,
    depth: claims.depth,
    tool_name: toolName,
    arguments: args,
  };
  try {
    const response = await fetcher(`${backendUrl}/internal/acp/tool-ingress-abort`, {
      method: "POST", headers: scopeHeaders(claims, proofToken), body: JSON.stringify(body),
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
    const payload = await jsonObject(response);
    if (!payload || !hasExactKeys(payload, ["schema_version", "mcp_request_id", "root_run_id",
      "runtime_boot_id", "native_root_session_id", "native_agent_session_id",
      "native_parent_session_id", "origin", "depth", "tool_name", "arguments_sha256",
      "sequence", "event_sha256", "outcome", "abort_sha256"])) return undefined;
    const receipt = payload as unknown as AcpToolIngressAbortReceipt;
    return receipt.schema_version === "byq-acp-tool-ingress-abort-receipt.v1"
      && receipt.mcp_request_id === mcpRequestId
      && receipt.root_run_id === claims.root_run_id
      && receipt.runtime_boot_id === claims.runtime_boot_id
      && receipt.native_root_session_id === claims.native_root_session_id
      && receipt.native_agent_session_id === claims.native_agent_session_id
      && receipt.native_parent_session_id === claims.native_parent_session_id
      && receipt.origin === claims.origin && receipt.depth === claims.depth
      && receipt.tool_name === toolName && receipt.outcome === "aborted_before_dispatch"
      && Number.isSafeInteger(receipt.sequence) && receipt.sequence > 0
      && SHA256.test(receipt.arguments_sha256) && SHA256.test(receipt.event_sha256)
      && SHA256.test(receipt.abort_sha256) ? receipt : undefined;
  } catch {
    return undefined;
  }
}

/** Close one exact ingress observation after its handler has a definitive or unknown outcome. No retry. */
export async function settleAcpToolIngress(
  backendUrl: string,
  proofToken: string,
  claims: AcpAgentClaims,
  ingress: AcpToolIngressReceipt,
  outcome: AcpToolIngressOutcome,
  fetcher: Fetcher = fetch,
): Promise<AcpToolIngressSettlementReceipt | undefined> {
  const headers = scopeHeaders(claims, proofToken);
  const body = {
    schema_version: "byq-acp-tool-ingress-settle.v1",
    mcp_request_id: ingress.mcp_request_id,
    root_run_id: ingress.root_run_id,
    runtime_boot_id: ingress.runtime_boot_id,
    native_root_session_id: claims.native_root_session_id,
    native_agent_session_id: ingress.native_agent_session_id,
    native_parent_session_id: claims.native_parent_session_id,
    origin: claims.origin,
    depth: claims.depth,
    tool_name: ingress.tool_name,
    sequence: ingress.sequence,
    event_sha256: ingress.event_sha256,
    outcome,
  };
  try {
    const response = await fetcher(`${backendUrl}/internal/acp/tool-ingress-settle`, {
      method: "POST", headers, body: JSON.stringify(body), signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
    const payload = await jsonObject(response);
    if (!payload || !hasExactKeys(payload, ["schema_version", "mcp_request_id", "root_run_id",
      "runtime_boot_id", "native_agent_session_id", "tool_name", "sequence", "event_sha256",
      "outcome", "settlement_sha256"])) return undefined;
    const receipt = payload as unknown as AcpToolIngressSettlementReceipt;
    const valid = receipt.schema_version === "byq-acp-tool-ingress-settle-receipt.v1"
      && receipt.mcp_request_id === ingress.mcp_request_id
      && receipt.root_run_id === claims.root_run_id
      && receipt.runtime_boot_id === claims.runtime_boot_id
      && receipt.native_agent_session_id === claims.native_agent_session_id
      && receipt.tool_name === ingress.tool_name
      && receipt.sequence === ingress.sequence
      && receipt.event_sha256 === ingress.event_sha256
      && receipt.outcome === outcome
      && MCP_REQUEST_ID.test(receipt.mcp_request_id)
      && ROOT_ID.test(receipt.root_run_id)
      && Number.isSafeInteger(receipt.sequence) && receipt.sequence > 0
      && SHA256.test(receipt.event_sha256)
      && SHA256.test(receipt.settlement_sha256);
    return valid ? receipt : undefined;
  } catch {
    return undefined;
  }
}

export async function bindAcpAgentRun(
  backendUrl: string,
  proofToken: string,
  claims: AcpAgentClaims,
  agentRunId: string,
  parentRunId: string | null,
  fetcher: Fetcher = fetch,
): Promise<AcpAgentBindReceipt | undefined> {
  if (!RUN_ID.test(agentRunId) || !isValidParentRunId(parentRunId, claims)) return undefined;
  const headers = scopeHeaders(claims, proofToken);
  const body = {
    schema_version: "byq-acp-agent-bind.v1",
    root_run_id: claims.root_run_id,
    runtime_boot_id: claims.runtime_boot_id,
    native_root_session_id: claims.native_root_session_id,
    native_agent_session_id: claims.native_agent_session_id,
    native_parent_session_id: claims.native_parent_session_id,
    origin: claims.origin,
    depth: claims.depth,
    agent_run_id: agentRunId,
    parent_run_id: parentRunId,
  };
  try {
    const response = await fetcher(`${backendUrl}/internal/acp/agent-bind`, {
      method: "POST", headers, body: JSON.stringify(body), signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
    const payload = await jsonObject(response);
    return payload && validBindReceipt(payload, claims, agentRunId, parentRunId)
      ? payload as AcpAgentBindReceipt : undefined;
  } catch {
    return undefined;
  }
}

function validBindingStatus(value: unknown, claims: AcpAgentClaims): value is AcpAgentBindingStatus {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const status = value as Record<string, unknown>;
  const common = ["schema_version", "root_run_id", "runtime_boot_id", "native_agent_session_id", "status"];
  if (status.schema_version !== "byq-acp-agent-binding-status.v1"
    || status.root_run_id !== claims.root_run_id || status.runtime_boot_id !== claims.runtime_boot_id
    || status.native_agent_session_id !== claims.native_agent_session_id) return false;
  if (status.status === "pending") return hasExactKeys(status, common);
  if (status.status !== "bound" || !hasExactKeys(status, [...common, "receipt"])) return false;
  return validBindReceipt(status.receipt, claims,
    String((status.receipt as Record<string, unknown>)?.agent_run_id),
    (status.receipt as Record<string, unknown>)?.parent_run_id as string | null);
}

/** Read-only outcome reconciliation after an unknown bind response; never binds again. */
export async function getAcpAgentBindingStatus(
  backendUrl: string,
  proofToken: string,
  claims: AcpAgentClaims,
  fetcher: Fetcher = fetch,
): Promise<AcpAgentBindingStatus | undefined> {
  const query = new URLSearchParams({ root_run_id: claims.root_run_id,
    native_agent_session_id: claims.native_agent_session_id });
  const headers = scopeHeaders(claims, proofToken);
  try {
    const response = await fetcher(`${backendUrl}/internal/acp/agent-binding?${query.toString()}`, {
      method: "GET", headers, signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
    const payload = await jsonObject(response);
    return payload && validBindingStatus(payload, claims) ? payload as AcpAgentBindingStatus : undefined;
  } catch {
    return undefined;
  }
}

export function observationReceiptHeader(receipt: AcpDomainObservationReceipt): string {
  return receipt.mcp_request_id;
}

export function addAcpObservationHeader(headers: Headers, observationId: string | undefined): Headers {
  if (observationId && MCP_REQUEST_ID.test(observationId)) {
    headers.set("x-byq-acp-observation-id", observationId);
  } else {
    headers.delete("x-byq-acp-observation-id");
  }
  return headers;
}
