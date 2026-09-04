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
