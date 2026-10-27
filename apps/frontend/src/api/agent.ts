import type { AgentSession, AgentSessionReplay, WorkflowTraceEvent } from "./types";

const AGENT_ROOT = "/v1/agent";
const WORKFLOW_ROOT = "/v1/workflows";
const PRODUCT_ROOT = "/api/product";

export const AGENT_EXECUTION_OPTIONS_SCHEMA = "agent-execution-options.v1" as const;

export interface AgentExecutionOptions {
  auto_continue: boolean;
  max_provider_calls: number | null;
  max_provider_attempts: number | null;
  max_tool_calls: number | null;
  max_concurrent_provider_calls: number | null;
  max_input_bytes_per_call: number | null;
  max_input_bytes_total: number | null;
  max_output_tokens_per_call: number | null;
  max_output_tokens_total: number | null;
  max_tool_payload_bytes_per_call: number | null;
  max_tool_payload_bytes_total: number | null;
  max_continuations: number | null;
  max_runtime_seconds: number | null;
  max_no_progress_seconds: number | null;
  max_child_runtime_seconds: number | null;
  max_child_no_progress_seconds: number | null;
}

export interface AgentExecutionOptionsRecord {
  schema_version: typeof AGENT_EXECUTION_OPTIONS_SCHEMA;
  conversation_id: string;
  owner_principal: string;
  workspace_id: string;
  revision: number;
  options: AgentExecutionOptions;
  updated_at: string | null;
}

export interface AgentExecutionOptionsUpdate {
  schema_version: typeof AGENT_EXECUTION_OPTIONS_SCHEMA;
  expected_revision: number;
  options: AgentExecutionOptions;
}

const executionOptionLimitFields = [
  "max_provider_calls", "max_provider_attempts", "max_tool_calls", "max_concurrent_provider_calls",
  "max_input_bytes_per_call", "max_input_bytes_total", "max_output_tokens_per_call", "max_output_tokens_total",
  "max_tool_payload_bytes_per_call", "max_tool_payload_bytes_total", "max_continuations", "max_runtime_seconds",
  "max_no_progress_seconds", "max_child_runtime_seconds", "max_child_no_progress_seconds",
] as const;

export function isAgentExecutionOptionsRecord(
  value: unknown,
  conversationId: string,
): value is AgentExecutionOptionsRecord {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  if (record.schema_version !== AGENT_EXECUTION_OPTIONS_SCHEMA
      || record.conversation_id !== conversationId
      || typeof record.owner_principal !== "string"
      || typeof record.workspace_id !== "string"
      || typeof record.revision !== "number" || !Number.isSafeInteger(record.revision) || record.revision < 0
      || typeof record.options !== "object" || record.options === null) return false;
  const options = record.options as Record<string, unknown>;
  const expectedFields = ["auto_continue", ...executionOptionLimitFields];
  if (Object.keys(options).length !== expectedFields.length
      || expectedFields.some((field) => !Object.prototype.hasOwnProperty.call(options, field))
      || typeof options.auto_continue !== "boolean") return false;
  return executionOptionLimitFields.every((field) => {
    const limit = options[field];
    return limit === null || (typeof limit === "number" && Number.isSafeInteger(limit) && limit > 0);
  });
}

export class AgentRequestError extends Error {
  constructor(message: string, readonly status: number, readonly code?: string) {
    super(message);
    this.name = "AgentRequestError";
  }
}

async function jsonRequest<T>(path: string, token: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "include",
    headers: {
      "content-type": "application/json",
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: unknown; error?: { code?: unknown; message?: unknown } };
    const maintenance = response.status === 503 && body.error?.code === "chat_maintenance";
    const unknownPrompt = response.status === 502 && body.error?.code === "prompt_outcome_unknown";
    const message = typeof body.error?.message === "string" ? body.error.message
      : typeof body.detail === "string" ? body.detail : "agent request failed";
    const productCode = typeof body.error?.code === "string" ? body.error.code : undefined;
    throw new AgentRequestError(message.slice(0, 500), response.status,
      productCode ?? (maintenance ? "chat_maintenance" : unknownPrompt ? "prompt_outcome_unknown" : undefined));
  }
  return (await response.json()) as T;
}

export function createAgentSession(token: string): Promise<AgentSession> {
  return jsonRequest<AgentSession>(`${AGENT_ROOT}/sessions`, token, { method: "POST" });
}

export function listAgentSessions(
  token: string,
  options: { status?: "active" | "archived"; search?: string; limit?: number; offset?: number } = {},
): Promise<{ sessions: AgentSession[]; total: number; limit: number; offset: number }> {
  const params = new URLSearchParams();
  if (options.status) params.set("status", options.status);
  if (options.search) params.set("search", options.search);
  if (options.limit) params.set("limit", String(options.limit));
  if (options.offset) params.set("offset", String(options.offset));
  const query = params.size ? `?${params}` : "";
  return jsonRequest(`${AGENT_ROOT}/sessions${query}`, token);
}

export function getAgentSession(sessionId: string, token: string): Promise<AgentSessionReplay> {
  return jsonRequest(`${AGENT_ROOT}/sessions/${encodeURIComponent(sessionId)}`, token);
}

export function updateAgentSession(
  sessionId: string,
  payload: { title?: string; pinned?: boolean; status?: "active" | "archived" },
  token: string,
): Promise<{ session: AgentSession }> {
  return jsonRequest(`${AGENT_ROOT}/sessions/${encodeURIComponent(sessionId)}`, token, {
    method: "PATCH", body: JSON.stringify(payload),
  });
}

export function submitTurn(
  sessionId: string,
  content: string,
  token: string,
): Promise<{ accepted: boolean; run_id?: string }> {
  return jsonRequest(`${AGENT_ROOT}/sessions/${encodeURIComponent(sessionId)}/turns`, token, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

export function resumeSession(sessionId: string, token: string): Promise<{ status?: string }> {
  return jsonRequest(`${AGENT_ROOT}/sessions/${encodeURIComponent(sessionId)}/resume`, token, { method: "POST" });
}

export function cancelSession(sessionId: string, mode: "soft" | "hard", token: string): Promise<{ status?: string }> {
  return jsonRequest(`${AGENT_ROOT}/sessions/${encodeURIComponent(sessionId)}/cancel`, token, {
    method: "POST",
    body: JSON.stringify({ mode }),
  });
}

export function getAgentExecutionOptions(
  conversationId: string,
  token: string,
): Promise<AgentExecutionOptionsRecord> {
  return jsonRequest<AgentExecutionOptionsRecord>(
    `${PRODUCT_ROOT}/agent/conversations/${encodeURIComponent(conversationId)}/execution-options`,
    token,
  );
}

export function updateAgentExecutionOptions(
  conversationId: string,
  payload: AgentExecutionOptionsUpdate,
  token: string,
): Promise<AgentExecutionOptionsRecord> {
  return jsonRequest<AgentExecutionOptionsRecord>(
    `${PRODUCT_ROOT}/agent/conversations/${encodeURIComponent(conversationId)}/execution-options`,
    token,
    { method: "PUT", body: JSON.stringify(payload) },
  );
}

export function deleteAgentSession(sessionId: string, token: string): Promise<{ status?: string }> {
  return jsonRequest(`${AGENT_ROOT}/sessions/${encodeURIComponent(sessionId)}`, token, { method: "DELETE" });
}

export async function streamWorkflowEvents(
  sessionId: string,
  token: string,
  onEvent: (event: WorkflowTraceEvent) => void,
  lastEventId = "0",
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${WORKFLOW_ROOT}/${encodeURIComponent(sessionId)}/events`, {
    credentials: "include",
    headers: {
      "Last-Event-ID": lastEventId,
      Accept: "text/event-stream",
    },
    signal,
  });
  if (!response.ok || !response.body) {
    const body = (await response.json().catch(() => ({}))) as { detail?: unknown; error?: { code?: unknown; message?: unknown } };
    const code = typeof body.error?.code === "string" ? body.error.code : undefined;
    const message = typeof body.error?.message === "string" ? body.error.message
      : typeof body.detail === "string" ? body.detail : "workflow stream failed";
    throw new AgentRequestError(message.slice(0, 500), response.status, code);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      try {
        onEvent(JSON.parse(line.slice(6)) as WorkflowTraceEvent);
      } catch {
        continue;
      }
    }
  }
  buffer += decoder.decode();
  for (const line of buffer.split("\n")) {
    if (!line.startsWith("data: ")) continue;
    try {
      onEvent(JSON.parse(line.slice(6)) as WorkflowTraceEvent);
    } catch {
      continue;
    }
  }
  throw new Error("workflow stream ended");
}
