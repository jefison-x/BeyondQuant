import { describe, expect, it } from "vitest";
import { foldWorkflowCards, workflowActivities, workflowOutcomes, workflowRunState, workflowWaiting } from "./workflow";
import type { WorkflowTraceEvent } from "./types";

function event(sequence: number, kind: string, payload: Record<string, unknown>): WorkflowTraceEvent {
  return {
    trace_id: "trace-1",
    session_id: "session-1",
    sequence,
    timestamp: "2026-08-22T00:00:00Z",
    kind,
    source: "runtime-adapter",
    payload,
  };
}

describe("workflow projections", () => {
  it.each(["domain-correction-stopped", "domain-call-reference-unproven", "domain-call-retention-bound"])(
    "keeps %s as a stopped outcome without blind retry", code => {
      const events = [event(1, "session.started", {}), event(2, "session.failed", { code, retryable: false })];
      expect(workflowOutcomes(events, "session-1")[0].message).toContain("停止");
      expect(workflowOutcomes(events, "session-1")[0].message).not.toContain("直接重试");
      expect(workflowRunState(events).retryable).toBe(false);
    });
  it("shows bounded waiting separately and clears it on terminal or next turn", () => {
    const wait = event(2, "session.waiting", { run_id: "run", elapsed_seconds: 60, last_activity_seconds: 20 });
    expect(workflowWaiting([event(1, "session.started", {}), wait], "session-1")).toEqual({ elapsed: 60, quiet: 20 });
    expect(workflowWaiting([wait], "other")).toBeNull();
    expect(workflowWaiting([wait, event(3, "session.result", {})], "session-1")).toBeNull();
    expect(workflowWaiting([wait, event(3, "session.started", {})], "session-1")).toBeNull();
    expect(workflowWaiting([event(2, "session.waiting", { elapsed_seconds: -1, last_activity_seconds: 20 })], "session-1")).toBeNull();
  });
  it("replays every historical outcome after later success without raw errors or duplicates", () => {
    const failure = event(2, "session.failed", { code: "runtime-subagent-timeout", error: "private-secret" });
    const events = [
      event(1, "session.started", {}), failure, event(3, "session.ready", {}),
      event(4, "session.started", {}), event(5, "session.cancelled", {}),
      event(6, "session.result.discarded", { reason: "private-secret" }),
      event(7, "session.started", {}), event(8, "session.result", {}), failure,
      { ...event(9, "session.failed", {}), session_id: "other-session" },
    ];
    const outcomes = workflowOutcomes([...events].reverse(), "session-1");
    expect(outcomes.map(item => item.sequence)).toEqual([2, 5, 6]);
    expect(outcomes.every(item => item.laterTurnStarted)).toBe(true);
    expect(outcomes[0].message).toContain("专项分析");
    expect(JSON.stringify(outcomes)).not.toContain("private-secret");
    expect(workflowOutcomes(events, "missing-session")).toEqual([]);
    expect(workflowOutcomes([failure, event(3, "session.resumed", {})], "session-1")[0].laterTurnStarted).toBe(false);
    for (const code of ["unknown-private-secret", "constructor", "__proto__"]) {
      expect(workflowOutcomes([event(2, "session.failed", { code })], "session-1")[0].message).toContain("本轮运行未能完成");
    }
  });

  it("folds cards by stable identity and highest revision", () => {
    const common = {
      schema_version: "workflow-card.v1",
      card_id: `card_${"a".repeat(64)}`,
      authority: "proposal",
      title: "草稿",
      truncated: false,
      name: "双均线",
      summary: "趋势",
    };
    const cards = foldWorkflowCards([
      event(1, "agent.card.strategy_draft", { ...common, revision: 1 }),
      event(2, "agent.card.strategy_draft", { ...common, revision: 2, title: "更新草稿" }),
    ]);
    expect(cards).toHaveLength(1);
    expect(cards[0].payload.title).toBe("更新草稿");
  });

  it("reads only normalized public activities", () => {
    const activities = workflowActivities([
      event(1, "agent.activity", {
        schema_version: "workflow-activity.v1",
        activity_id: `activity_${"b".repeat(64)}`,
        phase: "strategy",
        state: "started",
        label: "校验策略",
      }),
      event(2, "private.reasoning", { text: "hidden" }),
    ]);
    expect(activities).toHaveLength(1);
    expect(JSON.stringify(activities)).not.toContain("hidden");
  });

  it("closes orphaned public activities when the run has a terminal event", () => {
    const activities = workflowActivities([
      event(1, "agent.activity", {
        schema_version: "workflow-activity.v1",
        activity_id: `activity_${"c".repeat(64)}`,
        phase: "understand",
        state: "started",
        label: "理解请求",
      }),
      event(2, "session.failed", { code: "model-run-failed", retryable: true }),
    ]);
    expect(activities[0].payload.state).toBe("failed");
  });

  it("derives a replay-safe running state from lifecycle events", () => {
    expect(workflowRunState([event(3, "session.started", {})])).toEqual(expect.objectContaining({
      running: true, answerStarted: false,
    }));
    expect(workflowRunState([
      event(3, "session.started", {}), event(5, "agent.output.delta", { delta: "最终回答" }),
    ])).toEqual(expect.objectContaining({ running: true, answerStarted: true }));
    expect(workflowRunState([
      event(3, "session.started", {}), event(5, "agent.output.delta", { delta: "最终回答" }),
      event(7, "session.result", {}),
    ])).toEqual(expect.objectContaining({ running: false, answerStarted: false }));
    expect(workflowRunState([
      event(3, "session.started", {}), event(5, "agent.output.delta", { delta: "上一轮回答" }),
      event(7, "session.cancelled", {}), event(9, "session.started", {}),
    ])).toEqual(expect.objectContaining({ running: true, answerStarted: false }));
    expect(workflowRunState([
      event(3, "session.started", {}), event(7, "session.failed", { code: "model-run-failed", retryable: true }),
    ])).toEqual(expect.objectContaining({ running: false, failed: true, retryable: true }));
    expect(workflowRunState([
      event(3, "session.started", {}), event(7, "session.failed", { code: "model-run-failed", retryable: true }),
      event(8, "session.ready", { status: "ready" }),
      event(9, "session.resumed", { status: "ready" }),
    ])).toEqual(expect.objectContaining({
      running: false, failed: true, retryable: true, failureCode: "model-run-failed",
    }));
    expect(workflowRunState([
      event(3, "session.started", {}), event(7, "session.failed", { code: "model-run-failed", retryable: true }),
      event(8, "session.ready", { status: "ready" }), event(9, "session.started", {}),
    ])).toEqual(expect.objectContaining({ running: true, failed: false, retryable: false }));
  });
});
