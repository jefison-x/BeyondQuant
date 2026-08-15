const BACKEND_TIMEOUT_MS = 8000;

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

export type AgentContext = {
  owner_principal?: string;
  actor_principal?: string;
  trace_id?: string;
  session_id?: string;
  dsh_run_id?: string;
};

export type AgentResult = {
  content: Array<{ type: "text"; text: string }>;
  isError: boolean;
};

function result(payload: unknown, isError: boolean): AgentResult {
  return { content: [{ type: "text", text: JSON.stringify(payload) }], isError };
}
function errorStatus(status: number): string {
  if (status === 401) return "agent_unauthorized";
  if (status === 403) return "agent_forbidden";
  if (status === 404) return "agent_not_found";
  if (status === 409) return "agent_conflict";
  if (status === 422) return "agent_request_invalid";
  return "agent_unavailable";
}

function contextHeaders(context: AgentContext | undefined): Record<string, string> {
  if (!context) return {};
  const headers: Record<string, string> = {};
  const mapping: Array<[keyof AgentContext, string]> = [
    ["owner_principal", "x-byq-owner-principal"],
    ["actor_principal", "x-byq-actor-principal"],
    ["trace_id", "x-byq-trace-id"],
    ["session_id", "x-byq-session-id"],
    ["dsh_run_id", "x-byq-dsh-run-id"],
  ];
  for (const [field, header] of mapping) {
    const value = context[field];
    if (value) headers[header] = value;
  }
  return headers;
}

async function requestAgent(
  backendUrl: string,
  path: string,
  init: RequestInit,
  context: AgentContext | undefined,
  fetcher: Fetcher,
): Promise<AgentResult> {
  try {
    const response = await fetcher(`${backendUrl}${path}`, {
      ...init,
      headers: {
        "content-type": "application/json",
        ...contextHeaders(context),
        ...(init.headers ?? {}),
      },
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
    if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: "invalid_response" } }, true);
    }
    if (!response.ok) {
      return result({ service: "beyondquant-mcp", status: "error", backend: { status: errorStatus(response.status), http_status: response.status } }, true);
    }
    return result({ service: "beyondquant-mcp", status: "ok", ...payload }, false);
  } catch {
    return result({ service: "beyondquant-mcp", status: "error", backend: { status: "unreachable" } }, true);
  }
}

export function fetchByqAgentRoles(
  backendUrl: string,
  fetcher: Fetcher = fetch,
): Promise<AgentResult> {
  return requestAgent(backendUrl, "/v1/agents/roles", { method: "GET" }, undefined, fetcher);
}

export function fetchByqAgentRunStart(
  backendUrl: string,
  request: Record<string, unknown>,
  context: AgentContext,
  fetcher: Fetcher = fetch,
): Promise<AgentResult> {
  return requestAgent(backendUrl, "/v1/agents/runs", { method: "POST", body: JSON.stringify(request) }, context, fetcher);
}

export function fetchByqAgentAuthorize(
  backendUrl: string,
  request: Record<string, unknown>,
  context: AgentContext,
  fetcher: Fetcher = fetch,
): Promise<AgentResult> {
  return requestAgent(backendUrl, "/v1/agents/authorize", { method: "POST", body: JSON.stringify(request) }, context, fetcher);
}

export function fetchByqAgentAudit(
  backendUrl: string,
  request: Record<string, unknown>,
  context: AgentContext,
  fetcher: Fetcher = fetch,
): Promise<AgentResult> {
  return requestAgent(backendUrl, "/v1/agents/audit", { method: "POST", body: JSON.stringify(request) }, context, fetcher);
}

export function fetchByqAgentAuditGet(
  backendUrl: string,
  runId: string,
  context: AgentContext,
  fetcher: Fetcher = fetch,
): Promise<AgentResult> {
  return requestAgent(backendUrl, `/v1/agents/runs/${encodeURIComponent(runId)}/audit`, { method: "GET" }, context, fetcher);
}

export function fetchByqAgentApprovalRequest(
  backendUrl: string,
  request: Record<string, unknown>,
  context: AgentContext,
  fetcher: Fetcher = fetch,
): Promise<AgentResult> {
  return requestAgent(backendUrl, "/v1/agents/approvals", { method: "POST", body: JSON.stringify(request) }, context, fetcher);
}

export function fetchByqAgentApprovalGet(
  backendUrl: string,
  approvalId: string,
  context: AgentContext,
  fetcher: Fetcher = fetch,
): Promise<AgentResult> {
  return requestAgent(backendUrl, `/v1/agents/approvals/${encodeURIComponent(approvalId)}`, { method: "GET" }, context, fetcher);
}

export function fetchByqAgentApprovalDecide(
  backendUrl: string,
  approvalId: string,
  request: Record<string, unknown>,
  context: AgentContext,
  fetcher: Fetcher = fetch,
): Promise<AgentResult> {
  return requestAgent(backendUrl, `/v1/agents/approvals/${encodeURIComponent(approvalId)}/decision`, { method: "POST", body: JSON.stringify(request) }, context, fetcher);
}
