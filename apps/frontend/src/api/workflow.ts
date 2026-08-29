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
  const terminalSequence = events.reduce(
    (maximum, event) => TERMINAL_RUN_EVENTS.has(event.kind) ? Math.max(maximum, event.sequence) : maximum,
    -1,
  );
  return [...latest.values()]
    .map((activity) => terminalSequence > activity.sequence
      && ["started", "progress", "waiting_approval"].includes(activity.payload.state)
      ? { ...activity, payload: { ...activity.payload, state: "failed" as const } }
      : activity)
    .sort((left, right) => left.sequence - right.sequence)
    .slice(-20);
}

const TERMINAL_RUN_EVENTS = new Set([
  "session.result", "session.failed", "session.cancelled", "session.result.discarded",
]);

export function workflowRunState(events: WorkflowTraceEvent[]): {
  running: boolean;
  answerStarted: boolean;
  startedAt?: string;
  failed: boolean;
  retryable: boolean;
  failureCode?: string;
} {
  let started: WorkflowTraceEvent | undefined;
  let terminal: WorkflowTraceEvent | undefined;
  let answerSequence = -1;
  let recoverySequence = -1;
  for (const event of events) {
    if (event.kind === "session.started" && (!started || event.sequence > started.sequence)) started = event;
    if (TERMINAL_RUN_EVENTS.has(event.kind) && (!terminal || event.sequence > terminal.sequence)) terminal = event;
    if (event.kind === "agent.output.delta") answerSequence = Math.max(answerSequence, event.sequence);
    if (["session.ready", "session.resumed"].includes(event.kind)) {
      recoverySequence = Math.max(recoverySequence, event.sequence);
    }
  }
  const running = Boolean(started && started.sequence > (terminal?.sequence ?? -1));
  const answerStarted = Boolean(running && started && answerSequence > started.sequence);
  const failed = !running && terminal?.kind === "session.failed" && terminal.sequence > recoverySequence;
  return {
    running,
    answerStarted,
    startedAt: running ? started?.timestamp : undefined,
    failed,
    retryable: failed && terminal?.payload.retryable === true,
    failureCode: failed && typeof terminal?.payload.code === "string" ? terminal.payload.code : undefined,
  };
}
