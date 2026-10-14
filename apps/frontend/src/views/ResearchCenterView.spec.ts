import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import ElementPlus from "element-plus";
import { useAuthStore } from "@/stores/auth";
import ResearchCenterView from "./ResearchCenterView.vue";

const getApproval = vi.fn();
const getContinuationPermission = vi.fn();
const getResearchEntity = vi.fn();
const getTaskHandoff = vi.fn();
const listApprovals = vi.fn();
const listArtifacts = vi.fn();
const listProductApprovalRequests = vi.fn();
const listTasks = vi.fn();
const getStrategyVersionApproval = vi.fn();
let testPinia: ReturnType<typeof createPinia>;

vi.mock("@/api/research", () => ({
  getApproval: (...args: unknown[]) => getApproval(...args),
  getContinuationPermission: (...args: unknown[]) => getContinuationPermission(...args),
  getResearchEntity: (...args: unknown[]) => getResearchEntity(...args),
  getTaskHandoff: (...args: unknown[]) => getTaskHandoff(...args),
  listApprovals: (...args: unknown[]) => listApprovals(...args),
  listArtifacts: (...args: unknown[]) => listArtifacts(...args),
  listProductApprovalRequests: (...args: unknown[]) => listProductApprovalRequests(...args),
  listTasks: (...args: unknown[]) => listTasks(...args),
}));
vi.mock("@/api/quant", () => ({ getStrategyVersionApproval: (...args: unknown[]) => getStrategyVersionApproval(...args) }));

beforeEach(() => {
  testPinia = createPinia();
  setActivePinia(testPinia);
  useAuthStore().setUser({ subject: "alice", workspace: { workspace_id: "workspace-alice" } } as any);
  getApproval.mockResolvedValue({ approval: null });
  getContinuationPermission.mockResolvedValue({ task_id: `task_${"1".repeat(32)}`, permission: null });
  getResearchEntity.mockResolvedValue({});
  listApprovals.mockResolvedValue({ approvals: [], total: 0 });
  listArtifacts.mockResolvedValue({ artifacts: [] });
  listProductApprovalRequests.mockResolvedValue({ requests: [], total: 0 });
  listTasks.mockImplementation(() => Promise.resolve({ tasks: [{
    task_id: `task_${"1".repeat(32)}`, owner_principal: useAuthStore().user?.subject,
    workspace_id: useAuthStore().user?.workspace?.workspace_id,
    title: "当前任务", objective: "读取已有研究记录", status: "planned", conversation_id: "conversation-existing",
  }] }));
  getStrategyVersionApproval.mockResolvedValue({ approval: null });
});

it("keeps the Research page read-only and leaves approval writes to the Bell", async () => {
  const wrapper = mount(ResearchCenterView, {
    global: { plugins: [ElementPlus, testPinia], stubs: { TaskHandoffPanel: true } },
  });
  await flushPromises();
  expect(wrapper.text()).not.toContain("创建研究任务");
  expect(wrapper.text()).not.toContain("申请续接审批");
  expect(wrapper.text()).not.toContain("撤销后台续接许可");
  expect(wrapper.text()).toContain("读取已记录许可");
  expect(listTasks).toHaveBeenCalledOnce();
  expect(listArtifacts).toHaveBeenCalledOnce();
  expect(listApprovals).toHaveBeenCalledOnce();
  expect(listProductApprovalRequests).toHaveBeenCalledOnce();
  wrapper.unmount();
});

it("drops an old workspace's late product history after an account switch", async () => {
  const wrapper = mount(ResearchCenterView, {
    global: { plugins: [ElementPlus, testPinia], stubs: { TaskHandoffPanel: true } },
  });
  await flushPromises();
  let resolveOld: (value: unknown) => void = () => {};
  listProductApprovalRequests.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
  const vm = wrapper.vm as unknown as {
    loadProductHistory: () => Promise<void>;
    productRequests: Array<Record<string, unknown>>;
  };
  const oldLoad = vm.loadProductHistory();
  useAuthStore().setUser({ subject: "bob", workspace: { workspace_id: "workspace-bob" } } as any);
  await flushPromises();
  resolveOld({ requests: [{
    request_id: `approval_request_${"1".repeat(32)}`, request_type: "strategy_version", status: "approved",
    owner_principal: "alice", workspace_id: "workspace-alice", task_id: `task_${"1".repeat(32)}`,
    resource_artifact_id: `artifact_${"1".repeat(32)}`, content_sha256: "a".repeat(64),
    request_key: "00000000-0000-4000-8000-000000000007", created_at: "2026-10-14T00:00:00Z", updated_at: "2026-10-14T00:00:00Z",
    strategy_version_artifact_id: `artifact_${"1".repeat(32)}`,
  }], total: 1 });
  await oldLoad;

  expect(vm.productRequests).toEqual([]);
  wrapper.unmount();
});

it("drops a late Agent history page after an account switch", async () => {
  const wrapper = mount(ResearchCenterView, {
    global: { plugins: [ElementPlus, testPinia], stubs: { TaskHandoffPanel: true } },
  });
  await flushPromises();
  let resolveOld: (value: unknown) => void = () => {};
  listApprovals.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
  const vm = wrapper.vm as unknown as {
    loadAgentHistory: () => Promise<void>;
    approvals: Array<Record<string, unknown>>;
  };
  const oldLoad = vm.loadAgentHistory();
  listApprovals.mockResolvedValueOnce({ approvals: [{ approval_id: "bob_history", status: "approved" }], total: 1 });
  listProductApprovalRequests.mockResolvedValueOnce({ requests: [], total: 0, pending_count: 0, attention_count: 0 });
  useAuthStore().setUser({ subject: "bob", workspace: { workspace_id: "workspace-bob" } } as any);
  await flushPromises();
  resolveOld({ approvals: [{ approval_id: "alice_history", status: "approved" }], total: 1 });
  await oldLoad;

  expect(vm.approvals.map(item => item.approval_id)).toEqual(["bob_history"]);
  wrapper.unmount();
});
