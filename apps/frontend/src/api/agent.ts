import type { AgentSession, WorkflowTraceEvent } from "./types";

const AGENT_ROOT = "/v1/agent";
const WORKFLOW_ROOT = "/v1/workflows";

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
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail ?? "agent request failed");
  }
  return (await response.json()) as T;
}

export function createAgentSession(token: string): Promise<AgentSession> {
  return jsonRequest<AgentSession>(`${AGENT_ROOT}/sessions`, token, { method: "POST" });
}

export function listAgentSessions(token: string): Promise<{ sessions: AgentSession[] }> {
  return jsonRequest<{ sessions: AgentSession[] }>(`${AGENT_ROOT}/sessions`, token);
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

export function releaseSession(sessionId: string, token: string): Promise<{ status?: string }> {
  return jsonRequest(`${AGENT_ROOT}/sessions/${encodeURIComponent(sessionId)}`, token, { method: "DELETE" });
}

export async function streamWorkflowEvents(
  sessionId: string,
  token: string,
  onEvent: (event: WorkflowTraceEvent) => void,
  lastEventId = "0",
): Promise<void> {
  const response = await fetch(`${WORKFLOW_ROOT}/${encodeURIComponent(sessionId)}/events`, {
    credentials: "include",
    headers: {
      "Last-Event-ID": lastEventId,
      Accept: "text/event-stream",
    },
  });
  if (!response.ok || !response.body) {
    throw new Error("workflow stream failed");
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
}
