import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ApprovalManagementPanel from "./ApprovalManagementPanel.vue";

describe("ApprovalManagementPanel feedback approval", () => {
  it("localizes the exact product feedback action and resource", () => {
    const wrapper = mount(ApprovalManagementPanel, {
      props: { approvals: [{
        approval_id: "agent_approval_feedback", status: "pending", action: "byq_feedback_submit",
        resource_type: "product_feedback", resource_id: `feedback_${"a".repeat(32)}`,
        reason: "提交已经展示的公开候选快照",
      }] },
      global: { stubs: { ElButton: { template: "<button><slot /></button>" }, ElTag: true, ElEmpty: true } },
    });
    expect(wrapper.text()).toContain("提交产品反馈");
    expect(wrapper.text()).toContain("产品反馈 · feedback_");
  });
});

describe("ApprovalManagementPanel training approval", () => {
  it("shows trusted frozen inputs and disables approval when the preview is missing", async () => {
    const approval = {
      approval_id: "agent_approval_training", status: "pending", action: "byq_ml_training_create",
      resource_type: "ml_training_submission", resource_id: `mlwatch_${"a".repeat(32)}`,
      reason: "Agent-written reason",
      resource_preview: {
        schema_version: "ml-training-submission-preview.v1", watch_id: `mlwatch_${"a".repeat(32)}`,
        state: "prepared", task_id: "task_exact", ml_strategy_artifact_id: "artifact_exact",
        stock_pool_snapshot_id: "snapshot_exact", experiment_id: null,
        idempotency_key: "training-exact-key",
      },
    };
    const wrapper = mount(ApprovalManagementPanel, {
      props: { approvals: [approval] },
      global: { stubs: { ElButton: { props: ["disabled"], template: "<button :disabled='disabled'><slot /></button>" }, ElTag: true, ElEmpty: true } },
    });
    expect(wrapper.text()).toContain("task_exact");
    expect(wrapper.text()).toContain("artifact_exact");
    expect(wrapper.text()).toContain("snapshot_exact");
    expect(wrapper.text()).toContain("training-exact-key");
    expect(wrapper.find("button").attributes("disabled")).toBeUndefined();
    await wrapper.setProps({ approvals: [{ ...approval, resource_preview: null }] });
    expect(wrapper.text()).toContain("冻结提交详情不可用");
    expect(wrapper.find("button").attributes("disabled")).toBeDefined();
  });
});
