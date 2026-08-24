import { describe, expect, it } from "vitest";
import type { WorkflowCardEvent } from "@/api/types";
import { workflowCardDestination } from "./workflowCardNavigation";

const common = {
  trace_id: "trace-1", session_id: "session-1", sequence: 1,
  timestamp: "2026-08-24T00:00:00Z", source: "gateway",
};
const payload = {
  schema_version: "workflow-card.v1" as const, card_id: "card_11111111111111111111111111111111",
  revision: 1, authority: "domain" as const, title: "结果", truncated: false,
};

describe("workflowCardDestination", () => {
  it("maps normalized cards to BYQ-owned resource deep links and keeps the conversation", () => {
    const stock = { ...common, kind: "agent.card.stock_candidates", payload: { ...payload, authority: "proposal", pool_id: "pool-1", items: [] } } as WorkflowCardEvent;
    const strategy = { ...common, kind: "agent.card.strategy_draft", payload: { ...payload, authority: "proposal", name: "动量", artifact_id: "artifact-1" } } as WorkflowCardEvent;
    const optimization = { ...common, kind: "agent.card.optimization", payload: { ...payload, authority: "proposal", objective: "优化", changes: [], strategy_artifact_id: "artifact-2" } } as WorkflowCardEvent;
    const backtest = { ...common, kind: "agent.card.backtest_context", payload: { ...payload, job_id: "job-1", status: "completed" } } as WorkflowCardEvent;

    expect(workflowCardDestination(stock, "session-1")).toEqual({ path: "/stock-pool", query: { from: "agent", session: "session-1", pool: "pool-1" } });
    expect(workflowCardDestination(strategy, "session-1").query?.artifact).toBe("artifact-1");
    expect(workflowCardDestination(optimization, "session-1").query?.artifact).toBe("artifact-2");
    expect(workflowCardDestination(backtest, "session-1")).toEqual({ path: "/backtest", query: { from: "agent", session: "session-1", job: "job-1" } });
  });
});
