import { describe, expect, it } from "vitest";
import { foldWorkflowCards, workflowActivities, workflowRunState } from "./workflow";
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

  it("derives a replay-safe running state from lifecycle events", () => {
    expect(workflowRunState([event(3, "session.started", {})]).running).toBe(true);
    expect(workflowRunState([
      event(3, "session.started", {}), event(7, "session.result", {}),
    ]).running).toBe(false);
    expect(workflowRunState([
      event(3, "session.started", {}), event(7, "session.cancelled", {}), event(9, "session.started", {}),
    ]).running).toBe(true);
  });
});
