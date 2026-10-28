import { defineComponent, h } from "vue";
import { flushPromises, shallowMount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useAuthStore } from "@/stores/auth";
import ApprovalManagementPanel from "./ApprovalManagementPanel.vue";
import GlobalApprovalCenter from "./GlobalApprovalCenter.vue";

const listApprovals = vi.fn();
const decideApproval = vi.fn();
const listTasks = vi.fn();
const listArtifacts = vi.fn();
const getResearchEntity = vi.fn();
const pushRoute = vi.fn();
const routeState = { fullPath: "/approvals" };

vi.mock("vue-router", () => ({ useRouter: () => ({ push: pushRoute }), useRoute: () => routeState }));

vi.mock("@/api/research", () => ({
  listApprovals: (...args: unknown[]) => listApprovals(...args),
  decideApproval: (...args: unknown[]) => decideApproval(...args),
  listTasks: (...args: unknown[]) => listTasks(...args),
  listArtifacts: (...args: unknown[]) => listArtifacts(...args),
  getResearchEntity: (...args: unknown[]) => getResearchEntity(...args),
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
    routeState.fullPath = "/approvals";
    setActivePinia(createPinia());
    useAuthStore().setUser({ subject: "alice", workspace: { workspace_id: "workspace-alice" } } as any);
    listApprovals.mockResolvedValue({
      approvals: [
        { approval_id: "approval_pending", status: "pending", action: "run_backtest" },
        { approval_id: "approval_approved", status: "approved", action: "save_strategy" },
        { approval_id: "approval_rejected", status: "rejected", action: "create_pool" },
      ],
      total: 3,
      pending_count: 1,
      limit: 50,
      offset: 0,
    });
    decideApproval.mockResolvedValue({ approval: {
      approval_id: "approval_pending", status: "approved", conversation_id: "conversation_1",
      continuation_status: "submitted",
    } });
    listTasks.mockResolvedValue({ tasks: [] });
    listArtifacts.mockResolvedValue({ artifacts: [] });
    getResearchEntity.mockReset();
  });

  it("counts and displays only Agent approvals requiring a manual decision", async () => {
    const wrapper = shallowMount(GlobalApprovalCenter, {
      global: { stubs },
    });
    await flushPromises();

    expect(wrapper.get("button").attributes("aria-label")).toBe("审批中心，1 项待审批");
    expect(wrapper.findComponent(BadgeStub).props("value")).toBe(1);
    expect(wrapper.findComponent(BadgeStub).props("hidden")).toBe(false);
    expect(wrapper.findComponent(ApprovalManagementPanel).props("approvals")).toEqual([
      { approval_id: "approval_pending", status: "pending", action: "run_backtest" },
    ]);
    expect(listApprovals).toHaveBeenCalledWith({ status: "pending", limit: 20, offset: 0 });
  });

  it("opens the approval center drawer from the header bell", async () => {
    const wrapper = shallowMount(GlobalApprovalCenter, {
      global: { stubs },
    });
    await flushPromises();
    await wrapper.get("button").trigger("click");

    expect(wrapper.findComponent(DrawerStub).props("modelValue")).toBe(true);
    expect(wrapper.findComponent(DrawerStub).props("title")).toBe("审批中心");
  });

  it("decides centrally and returns to the originating conversation", async () => {
    const wrapper = shallowMount(GlobalApprovalCenter, { global: { stubs } });
    await flushPromises();
    wrapper.findComponent(ApprovalManagementPanel).vm.$emit(
      "decide", { approval_id: "approval_pending", status: "pending" }, "approved",
    );
    await flushPromises();

    expect(decideApproval).toHaveBeenCalledWith(
      "approval_pending", "approved", "BYQ Product 人工审批",
    );
    expect(pushRoute).toHaveBeenCalledWith({ path: "/agent", query: { session: "conversation_1" } });
  });

  it("does not restore a previous owner's Agent approval list after a scope switch", async () => {
    let resolveOld: (value: unknown) => void = () => {};
    listApprovals.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    const wrapper = shallowMount(GlobalApprovalCenter, { global: { stubs } });
    await flushPromises();
    listApprovals.mockResolvedValueOnce({
      approvals: [{ approval_id: "bob_approval", status: "pending" }], total: 1, pending_count: 1,
    });
    useAuthStore().setUser({ subject: "bob", workspace: { workspace_id: "workspace-bob" } } as any);
    await flushPromises();
    resolveOld({ approvals: [{ approval_id: "alice_approval", status: "pending" }], total: 9, pending_count: 9 });
    await flushPromises();

    const vm = wrapper.vm as unknown as { approvals: Array<Record<string, unknown>>; pendingTotal: number };
    expect(vm.approvals.map(item => item.approval_id)).toEqual(["bob_approval"]);
    expect(vm.pendingTotal).toBe(1);
    wrapper.unmount();
  });

  it("does not navigate or show a late Agent decision after the signed-in scope changes", async () => {
    let resolveDecision: (value: unknown) => void = () => {};
    decideApproval.mockImplementationOnce(() => new Promise(resolve => { resolveDecision = resolve; }));
    const wrapper = shallowMount(GlobalApprovalCenter, { global: { stubs } });
    await flushPromises();
    wrapper.findComponent(ApprovalManagementPanel).vm.$emit(
      "decide", { approval_id: "approval_pending", status: "pending" }, "approved",
    );
    await flushPromises();
    listApprovals.mockResolvedValueOnce({ approvals: [], total: 0, pending_count: 0 });
    useAuthStore().setUser({ subject: "bob", workspace: { workspace_id: "workspace-bob" } } as any);
    await flushPromises();
    resolveDecision({ approval: {
      approval_id: "approval_pending", status: "approved", conversation_id: "alice_conversation",
      continuation_status: "submitted",
    } });
    await flushPromises();

    expect(pushRoute).not.toHaveBeenCalled();
    expect((wrapper.vm as unknown as { approvals: unknown[] }).approvals).toEqual([]);
    wrapper.unmount();
  });

  it("does not redirect after the user navigates away while an Agent decision is pending", async () => {
    let resolveDecision: (value: unknown) => void = () => {};
    decideApproval.mockImplementationOnce(() => new Promise(resolve => { resolveDecision = resolve; }));
    const wrapper = shallowMount(GlobalApprovalCenter, { global: { stubs } });
    await flushPromises();
    wrapper.findComponent(ApprovalManagementPanel).vm.$emit(
      "decide", { approval_id: "approval_pending", status: "pending" }, "approved",
    );
    await flushPromises();
    routeState.fullPath = "/research";
    resolveDecision({ approval: {
      approval_id: "approval_pending", status: "approved", conversation_id: "alice_conversation",
      continuation_status: "submitted",
    } });
    await flushPromises();

    expect(pushRoute).not.toHaveBeenCalled();
    expect((wrapper.vm as unknown as { approvals: unknown[] }).approvals).toEqual([
      { approval_id: "approval_pending", status: "pending", action: "run_backtest" },
      { approval_id: "approval_approved", status: "approved", action: "save_strategy" },
      { approval_id: "approval_rejected", status: "rejected", action: "create_pool" },
    ]);
    wrapper.unmount();
  });

  it("discards late task and Artifact candidates after the signed-in scope changes", async () => {
    let resolveTasks: (value: unknown) => void = () => {};
    let resolveArtifacts: (value: unknown) => void = () => {};
    listTasks.mockImplementationOnce(() => new Promise(resolve => { resolveTasks = resolve; }));
    listArtifacts.mockImplementationOnce(() => new Promise(resolve => { resolveArtifacts = resolve; }));
    const wrapper = shallowMount(GlobalApprovalCenter, { global: { stubs } });
    await flushPromises();
    const vm = wrapper.vm as unknown as {
      loadContinuationCandidates: () => Promise<void>;
      tasks: Array<Record<string, unknown>>;
      artifacts: Array<Record<string, unknown>>;
      continuationTask: string;
    };
    const pendingLoad = vm.loadContinuationCandidates();
    vm.tasks = [{ task_id: `task_${"a".repeat(32)}`, owner_principal: "alice", workspace_id: "workspace-alice" }];
    vm.artifacts = [{ artifact_id: `artifact_${"a".repeat(32)}`, owner_principal: "alice", workspace_id: "workspace-alice" }];
    vm.continuationTask = `task_${"a".repeat(32)}`;
    useAuthStore().setUser({ subject: "bob", workspace: { workspace_id: "workspace-bob" } } as any);
    expect(vm.tasks).toEqual([]);
    expect(vm.artifacts).toEqual([]);
    expect(vm.continuationTask).toBe("");
    await flushPromises();
    resolveTasks({ tasks: [{ task_id: `task_${"1".repeat(32)}`, owner_principal: "alice", workspace_id: "workspace-alice", conversation_id: "conversation-alice" }] });
    resolveArtifacts({ artifacts: [{ artifact_id: `artifact_${"1".repeat(32)}`, owner_principal: "alice", workspace_id: "workspace-alice" }] });
    await pendingLoad;
    expect(vm.tasks).toEqual([]);
    expect(vm.artifacts).toEqual([]);
    expect(vm.continuationTask).toBe("");
    wrapper.unmount();
  });

  it("uses an exact Product Task GET when the task is outside the capped candidate list", async () => {
    const taskId = `task_${"f".repeat(32)}`;
    listTasks.mockResolvedValueOnce({ tasks: Array.from({ length: 200 }, (_, index) => ({
      task_id: `task_${String(index).padStart(32, "0")}`,
      owner_principal: "alice", workspace_id: "workspace-alice", conversation_id: `conversation_${index}`,
    })) });
    listArtifacts.mockResolvedValueOnce({ artifacts: [] });
    const exactTask = {
      task_id: taskId, owner_principal: "alice", workspace_id: "workspace-alice",
      conversation_id: `conversation_${"f".repeat(32)}`, title: "精确任务",
    };
    getResearchEntity.mockResolvedValue(exactTask);
    const wrapper = shallowMount(GlobalApprovalCenter, { global: { stubs } });
    await flushPromises();
    const vm = wrapper.vm as unknown as {
      exactTaskId: string;
      loadExactContinuationTask: () => Promise<void>;
      loadContinuationCandidates: () => Promise<void>;
      tasks: Array<Record<string, unknown>>;
      continuationTask: string;
      taskListCapped: boolean;
    };
    await vm.loadContinuationCandidates();
    expect(vm.tasks).toHaveLength(200);
    expect(vm.taskListCapped).toBe(true);
    vm.exactTaskId = taskId;
    await vm.loadExactContinuationTask();
    expect(getResearchEntity).toHaveBeenCalledWith("tasks", taskId);
    expect(vm.tasks).toContainEqual(exactTask);
    expect(vm.continuationTask).toBe(taskId);
    wrapper.unmount();
  });
});
