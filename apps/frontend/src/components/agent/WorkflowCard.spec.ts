import { shallowMount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { WorkflowCardEvent } from "@/api/types";
import WorkflowCard from "./WorkflowCard.vue";

const pendingApproval = {
  trace_id: "trace-1",
  session_id: "session-1",
  sequence: 1,
  timestamp: "2026-08-24T00:00:00Z",
  source: "byq-domain",
  kind: "agent.card.approval",
  payload: {
    schema_version: "workflow-card.v1",
    card_id: "card_11111111111111111111111111111111",
    revision: 1,
    authority: "domain",
    title: "执行回测",
    truncated: false,
    approval_id: "approval_1",
    action: "run_backtest",
    status: "pending",
    execution_outcome: "not_started",
  },
} as WorkflowCardEvent;

describe("WorkflowCard", () => {
  it("keeps approval cards informational and delegates decisions to the header bell", () => {
    const wrapper = shallowMount(WorkflowCard, { props: { event: pendingApproval } });

    expect(wrapper.text()).toContain("请在右上角铃铛处理");
    expect(wrapper.text()).not.toContain("通过");
    expect(wrapper.text()).not.toContain("拒绝");
  });
});
