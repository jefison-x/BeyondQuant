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
    runId: string;
  }>();
  let activeRunId = "";
  for (const event of [...events].sort((a, b) => a.sequence - b.sequence)
    .filter(
      (event) => event.kind === "session.started" || (event.kind === "agent.activity"
        && event.payload?.schema_version === "workflow-activity.v1"
        && typeof event.payload?.activity_id === "string"),
    )
  ) {
    if (event.kind === "session.started") {
      activeRunId = typeof event.payload.run_id === "string" ? event.payload.run_id : "";
      continue;
    }
    latest.set(String(event.payload.activity_id), {
      sequence: event.sequence,
      timestamp: event.timestamp,
      payload: event.payload as unknown as WorkflowActivityPayload,
      runId: activeRunId,
    });
  }
  return [...latest.values()]
    .map((activity) => {
      const terminal = [...events].sort((a, b) => a.sequence - b.sequence).find(event => {
        if (!TERMINAL_RUN_EVENTS.has(event.kind) || event.sequence <= activity.sequence) return false;
        const terminalRunId = typeof event.payload.run_id === "string" ? event.payload.run_id : "";
        return activity.runId && terminalRunId
          ? activity.runId === terminalRunId
          : !activity.runId && !terminalRunId;
      });
      if (!terminal || !["started", "progress"].includes(activity.payload.state)) return activity;
      const state: WorkflowActivityPayload["state"] = terminal.kind === "session.cancelled" ? "cancelled"
        : terminal.kind === "session.failed" ? "failed" : "unknown";
      return { ...activity, payload: { ...activity.payload, state } };
    })
    .sort((left, right) => left.sequence - right.sequence)
    .slice(-20);
}

const TERMINAL_RUN_EVENTS = new Set([
  "session.result", "session.failed", "session.cancelled", "session.result.discarded",
]);

export function workflowWaiting(events: WorkflowTraceEvent[], sessionId: string) {
  let waiting: { elapsed: number; quiet: number } | null = null;
  let active = false;
  let runId = "";
  let startSequence = -1;
  for (const event of [...events].filter(item => item.session_id === sessionId)
    .sort((a, b) => a.sequence - b.sequence)) {
    if (event.kind === "session.started") {
      waiting = null;
      active = true;
      runId = typeof event.payload.run_id === "string" ? event.payload.run_id : "";
      startSequence = event.sequence;
    }
    else if (active && TERMINAL_RUN_EVENTS.has(event.kind)) {
      const terminalRunId = typeof event.payload.run_id === "string" ? event.payload.run_id : "";
      const matchesActiveRun = runId && terminalRunId ? runId === terminalRunId
        : !runId && !terminalRunId && event.sequence > startSequence;
      if (matchesActiveRun) {
        waiting = null;
        active = false;
        runId = "";
      }
    }
    else if (active && event.kind === "session.waiting" && event.source === "runtime-adapter"
      && (!runId || runId === event.payload.run_id)
      && Number.isInteger(event.payload.elapsed_seconds) && Number.isInteger(event.payload.last_activity_seconds)
      && Number(event.payload.elapsed_seconds) >= 0 && Number(event.payload.last_activity_seconds) >= 0) {
      waiting = { elapsed: Number(event.payload.elapsed_seconds), quiet: Number(event.payload.last_activity_seconds) };
    }
  }
  return waiting;
}

const FAILURE_MESSAGES: Record<string, string> = {
  "model-request-rejected": "模型服务拒绝了本轮请求，系统不会自动重试。请联系管理员检查模型接入配置；对话内容已保留。",
  "domain-correction-stopped": "本轮策略校验已停止，系统不会继续重复调用。请核对当前方案和已有结果后，再发起新的请求。",
  "domain-call-reference-unproven": "本轮调用缺少可核验的任务关联，系统已停止执行且不会自动重试。请确认研究对象后，再发起新的请求。",
  "domain-call-retention-bound": "本轮已达到调用记录上限，系统已停止继续调用。请检查已有结果并缩小后续研究范围。",
  "runtime-no-progress-timeout": "本轮在较长时间内没有形成可展示的结论，系统为避免持续占用已停止。已完成的读取步骤仍保留，可以直接重试。",
  "runtime-run-timeout": "本轮总处理时间超过运行上限，系统已停止任务。对话内容已保留，可以直接重试或缩小分析范围。",
  "runtime-subagent-timeout": "本轮专项分析超过等待上限，系统已停止任务。对话内容已保留，可以直接重试。",
  "model-run-failed": "模型服务本轮未能完成回答。对话内容已保留；请新建会话继续，若持续失败请联系管理员。",
  "budget-exhausted": "本轮已达到模型预算上限，系统已停止本轮且不会自动重试。对话仍可继续；请明确重述要执行的具体指令后再次发送。",
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
      ? "本轮已取消。已提交的业务任务请先核对实际状态，取消对话不代表撤销业务操作。接续子助手工作时会新建子助手，不会恢复原实例，也不会自动重做原任务。"
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
  let latestTerminal: WorkflowTraceEvent | undefined;
  let answerSequence = -1;
  for (const event of events) {
    if (event.kind === "session.started" && (!started || event.sequence > started.sequence)) started = event;
    if (TERMINAL_RUN_EVENTS.has(event.kind) && (!latestTerminal || event.sequence > latestTerminal.sequence)) latestTerminal = event;
    if (event.kind === "agent.output.delta") answerSequence = Math.max(answerSequence, event.sequence);
  }
  const startedRunId = typeof started?.payload.run_id === "string" ? started.payload.run_id : "";
  const terminal = startedRunId
    ? events.filter(event => TERMINAL_RUN_EVENTS.has(event.kind) && event.payload.run_id === startedRunId)
      .reduce<WorkflowTraceEvent | undefined>((latest, event) =>
        !latest || event.sequence > latest.sequence ? event : latest, undefined)
    : latestTerminal && (!started || latestTerminal.sequence > started.sequence) ? latestTerminal : undefined;
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
