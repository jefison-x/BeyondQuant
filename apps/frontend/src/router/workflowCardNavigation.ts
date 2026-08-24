import type { WorkflowCardEvent } from "@/api/types";

export interface WorkflowCardDestination {
  path: string;
  query?: Record<string, string>;
}

export function workflowCardDestination(event: WorkflowCardEvent, sessionId = ""): WorkflowCardDestination {
  const context: Record<string, string> = sessionId
    ? { from: "agent", session: sessionId }
    : { from: "agent" };
  if (event.kind === "agent.card.stock_candidates") {
    return { path: "/stock-pool", query: event.payload.pool_id ? { ...context, pool: event.payload.pool_id } : context };
  }
  if (event.kind === "agent.card.backtest_context") {
    return { path: "/backtest", query: { ...context, job: event.payload.job_id } };
  }
  if (event.kind === "agent.card.approval") return { path: "/user/research", query: context };
  const artifact = event.kind === "agent.card.optimization"
    ? event.payload.strategy_artifact_id
    : event.payload.artifact_id;
  return { path: "/strategy", query: artifact ? { ...context, artifact } : context };
}
