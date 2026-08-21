import type {
  WorkflowActivityPayload,
  WorkflowCardEvent,
  WorkflowCardKind,
  WorkflowTraceEvent,
} from "./types";

const CARD_KINDS = new Set<WorkflowCardKind>([
  "agent.card.strategy_draft",
  "agent.card.stock_candidates",
  "agent.card.optimization",
  "agent.card.backtest_context",
  "agent.card.approval",
]);

export function isWorkflowCard(event: WorkflowTraceEvent): event is WorkflowCardEvent {
  return CARD_KINDS.has(event.kind as WorkflowCardKind)
    && event.payload?.schema_version === "workflow-card.v1"
    && typeof event.payload?.card_id === "string"
    && typeof event.payload?.revision === "number";
}

export function foldWorkflowCards(events: WorkflowTraceEvent[]): WorkflowCardEvent[] {
  const latest = new Map<string, WorkflowCardEvent>();
  for (const event of events) {
    if (!isWorkflowCard(event)) continue;
    const previous = latest.get(event.payload.card_id);
    if (!previous || event.payload.revision > previous.payload.revision) {
      latest.set(event.payload.card_id, event);
    }
  }
  return [...latest.values()].sort((left, right) => left.sequence - right.sequence);
}

export function workflowActivities(events: WorkflowTraceEvent[]): Array<{
  sequence: number;
  timestamp: string;
  payload: WorkflowActivityPayload;
}> {
  const latest = new Map<string, {
    sequence: number;
    timestamp: string;
    payload: WorkflowActivityPayload;
  }>();
  for (const event of events
    .filter(
      (event) => event.kind === "agent.activity"
        && event.payload?.schema_version === "workflow-activity.v1"
        && typeof event.payload?.activity_id === "string",
    )
  ) {
    latest.set(String(event.payload.activity_id), {
      sequence: event.sequence,
      timestamp: event.timestamp,
      payload: event.payload as unknown as WorkflowActivityPayload,
    });
  }
  return [...latest.values()].sort((left, right) => left.sequence - right.sequence).slice(-20);
}
