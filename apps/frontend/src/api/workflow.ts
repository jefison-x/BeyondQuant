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

const FAILURE_MESSAGES: Record<string, string> = {
  "runtime-no-progress-timeout": "本轮在较长时间内没有形成可展示的结论，系统为避免持续占用已停止。已完成的读取步骤仍保留，可以直接重试。",
  "runtime-run-timeout": "本轮总处理时间超过运行上限，系统已停止任务。对话内容已保留，可以直接重试或缩小分析范围。",
  "runtime-subagent-timeout": "本轮专项分析超过等待上限，系统已停止任务。对话内容已保留，可以直接重试。",
  "model-run-failed": "模型服务本轮未能完成回答。对话内容已保留，可以直接重试；若持续失败，请联系管理员。",
};

/** Historical outcomes are operational records, never assistant answers or commands. */
export function workflowOutcomes(events: WorkflowTraceEvent[], sessionId: string) {
  const ordered = [...events].filter(event => event.session_id === sessionId)
    .sort((left, right) => left.sequence - right.sequence);
  const latestStart = ordered.reduce((sequence, event) =>
    event.kind === "session.started" ? Math.max(sequence, event.sequence) : sequence, -1);
  const seen = new Set<number>();
  return ordered.flatMap(event => {
    if (!TERMINAL_RUN_EVENTS.has(event.kind) || event.kind === "session.result" || seen.has(event.sequence)) return [];
    seen.add(event.sequence);
    const code = typeof event.payload.code === "string" ? event.payload.code : "";
    const message = event.kind === "session.cancelled"
      ? "本轮已取消。已提交的业务任务请查看其实际状态，取消对话不代表撤销业务操作。"
      : event.kind === "session.result.discarded"
        ? "本轮迟到结果未被采纳。已提交的业务任务请查看其实际状态。"
        : Object.hasOwn(FAILURE_MESSAGES, code) ? FAILURE_MESSAGES[code]!
          : "本轮运行未能完成。对话内容已保留；已提交的业务操作请先核实状态。";
    return [{
      key: `${event.session_id}:${event.sequence}`,
      sequence: event.sequence,
      timestamp: event.timestamp,
      message,
      laterTurnStarted: latestStart > event.sequence,
    }];
  });
}

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
  for (const event of events) {
    if (event.kind === "session.started" && (!started || event.sequence > started.sequence)) started = event;
    if (TERMINAL_RUN_EVENTS.has(event.kind) && (!terminal || event.sequence > terminal.sequence)) terminal = event;
    if (event.kind === "agent.output.delta") answerSequence = Math.max(answerSequence, event.sequence);
  }
  const running = Boolean(started && started.sequence > (terminal?.sequence ?? -1));
  const answerStarted = Boolean(running && started && answerSequence > started.sequence);
  // A passive runtime recreation emits ready/resumed without retrying the
  // failed turn. Preserve that failure until a later session.started event
  // proves that a new run actually began.
  const failed = !running && terminal?.kind === "session.failed";
  return {
    running,
    answerStarted,
    startedAt: running ? started?.timestamp : undefined,
    failed,
    retryable: failed && terminal?.payload.retryable === true,
    failureCode: failed && typeof terminal?.payload.code === "string" ? terminal.payload.code : undefined,
  };
}
