import { defineComponent, h } from "vue";
import { flushPromises, shallowMount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ApprovalManagementPanel from "./ApprovalManagementPanel.vue";
import GlobalApprovalCenter from "./GlobalApprovalCenter.vue";

const listApprovals = vi.fn();
const getApproval = vi.fn();
const decideApproval = vi.fn();

vi.mock("@/api/research", () => ({
  listApprovals: (...args: unknown[]) => listApprovals(...args),
  getApproval: (...args: unknown[]) => getApproval(...args),
  decideApproval: (...args: unknown[]) => decideApproval(...args),
}));

const DrawerStub = defineComponent({
  name: "ElDrawer",
  props: { modelValue: Boolean, title: String },
  emits: ["update:modelValue", "open"],
  setup(_, { slots }) {
    return () => h("div", slots.default?.());
  },
});

const PassThroughStub = defineComponent({
  setup(_, { slots }) {
    return () => h("div", slots.default?.());
  },
});

const BadgeStub = defineComponent({
  name: "ElBadge",
  props: { value: Number, hidden: Boolean },
  setup(_, { slots }) {
    return () => h("span", slots.default?.());
  },
});

const stubs = {
  ElDrawer: DrawerStub,
  ElTooltip: PassThroughStub,
  ElBadge: BadgeStub,
  ElIcon: PassThroughStub,
};

describe("GlobalApprovalCenter", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listApprovals.mockResolvedValue({
      approvals: [
        { approval_id: "approval_pending", status: "pending", action: "run_backtest" },
        { approval_id: "approval_approved", status: "approved", action: "save_strategy" },
        { approval_id: "approval_rejected", status: "rejected", action: "create_pool" },
      ],
    });
  });

  it("counts and displays only approvals requiring a manual decision", async () => {
    const wrapper = shallowMount(GlobalApprovalCenter, {
      global: { stubs },
    });
    await flushPromises();

    expect(wrapper.get("button").attributes("aria-label")).toBe("待人工审批，1 项");
    expect(wrapper.findComponent(BadgeStub).props("value")).toBe(1);
    expect(wrapper.findComponent(BadgeStub).props("hidden")).toBe(false);
    expect(wrapper.findComponent(ApprovalManagementPanel).props("approvals")).toEqual([
      { approval_id: "approval_pending", status: "pending", action: "run_backtest" },
    ]);
  });

  it("opens the manual approval drawer from the header bell", async () => {
    const wrapper = shallowMount(GlobalApprovalCenter, {
      global: { stubs },
    });
    await flushPromises();
    await wrapper.get("button").trigger("click");

    expect(wrapper.findComponent(DrawerStub).props("modelValue")).toBe(true);
    expect(wrapper.findComponent(DrawerStub).props("title")).toBe("待人工审批");
  });
});
