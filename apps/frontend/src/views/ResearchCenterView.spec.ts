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
vi.mock("@/api/quant", () => ({
  getStrategyVersionApproval: (...args: unknown[]) => getStrategyVersionApproval(...args),
}));

beforeEach(() => {
  testPinia = createPinia();
  setActivePinia(testPinia);
  const auth = useAuthStore();
  auth.token = "alice-token";
  auth.setUser({ subject: "alice", workspace: { workspace_id: "workspace-alice" } } as any);
  getApproval.mockReset();
  getApproval.mockResolvedValue({ approval_id: "approval_alice", status: "approved" });
  getContinuationPermission.mockReset();
  getContinuationPermission.mockImplementation((taskId: string) =>
    Promise.resolve({ task_id: taskId, permission: null }));
  getResearchEntity.mockReset();
  getTaskHandoff.mockReset();
  listApprovals.mockReset();
  listApprovals.mockResolvedValue({ approvals: [], total: 0 });
  listArtifacts.mockReset();
  listArtifacts.mockResolvedValue({ artifacts: [] });
  listProductApprovalRequests.mockReset();
  listProductApprovalRequests.mockResolvedValue({
    schema_version: "byq-product-approval-request-list.v1",
    requests: [],
    total: 0,
    pending_count: 0,
    attention_count: 0,
    limit: 20,
    offset: 0,
  });
  listTasks.mockReset();
  listTasks.mockResolvedValue({ tasks: [] });
  getStrategyVersionApproval.mockReset();
  getStrategyVersionApproval.mockResolvedValue({ approval: null });
});

function mountView() {
  return mount(ResearchCenterView, { global: { plugins: [ElementPlus, testPinia] } });
}

it("shows only read-only approval histories and does not load tasks, assets, or entities", async () => {
  const wrapper = mountView();
  await flushPromises();

  const pageText = wrapper.text();
  expect(pageText).toContain("审批历史");
  expect(pageText).toContain("Agent 审批历史");
  expect(pageText).toContain("BYQ 业务审批历史");
  expect(pageText).toContain("精确历史详情");
  expect(pageText).not.toContain("研究任务");
  expect(pageText).not.toContain("研究资产");
  expect(pageText).not.toContain("实体查询");
  expect(pageText).not.toContain("审批收件箱");
  const buttonText = wrapper.findAll("button").map(button => button.text()).join(" ");
  expect(buttonText).not.toMatch(/批准|拒绝|撤销|提交续接许可申请/);

  expect(listTasks).not.toHaveBeenCalled();
  expect(listArtifacts).not.toHaveBeenCalled();
  expect(getResearchEntity).not.toHaveBeenCalled();
  expect(getTaskHandoff).not.toHaveBeenCalled();
  expect(listApprovals).toHaveBeenCalledOnce();
  expect(listProductApprovalRequests).toHaveBeenCalledOnce();
  expect(getApproval).not.toHaveBeenCalled();
  expect(getContinuationPermission).not.toHaveBeenCalled();
  expect(getStrategyVersionApproval).not.toHaveBeenCalled();
  wrapper.unmount();
});

it("keeps exact Agent, strategy, and continuation history lookups read-only", async () => {
  const wrapper = mountView();
  await flushPromises();
  const taskId = "task_" + "1".repeat(32);
  const artifactId = "artifact_" + "a".repeat(32);
  const vm = wrapper.vm as unknown as {
    tab: string;
    approvalId: string;
    approvalSource: "agent" | "strategy" | "continuation";
    loadApproval: () => Promise<void>;
  };

  vm.tab = "approval-record";
  vm.approvalSource = "agent";
  vm.approvalId = "approval_alice";
  await vm.loadApproval();
  expect(getApproval).toHaveBeenCalledWith("approval_alice");

  vm.approvalSource = "strategy";
  vm.approvalId = artifactId;
  await vm.loadApproval();
  expect(getStrategyVersionApproval).toHaveBeenCalledWith(artifactId, "alice-token");

  vm.approvalSource = "continuation";
  vm.approvalId = taskId;
  await vm.loadApproval();
  expect(getContinuationPermission).toHaveBeenCalledWith(taskId);
  expect(getResearchEntity).not.toHaveBeenCalled();
  wrapper.unmount();
});

it("drops an old workspace's late product history after an account switch", async () => {
  const wrapper = mountView();
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
  resolveOld({
    schema_version: "byq-product-approval-request-list.v1",
    requests: [{
      request_id: "approval_request_" + "1".repeat(32), request_type: "strategy_version", status: "approved",
      owner_principal: "alice", workspace_id: "workspace-alice", task_id: "task_" + "1".repeat(32),
      resource_artifact_id: "artifact_" + "1".repeat(32), content_sha256: "a".repeat(64),
      request_key: "00000000-0000-4000-8000-000000000007",
      created_at: "2026-10-14T00:00:00Z", updated_at: "2026-10-14T00:00:00Z",
      decision: "approved", decision_key: "00000000-0000-4000-8000-000000000008",
      decision_by: "reviewer", decision_at: "2026-10-14T00:00:00Z", rationale: "approved in scope",
      domain_artifact_id: "artifact_" + "b".repeat(32),
      strategy_version_artifact_id: "artifact_" + "1".repeat(32),
    }],
    total: 1, pending_count: 0, attention_count: 0, limit: 20, offset: 0,
  });
  await oldLoad;

  expect(vm.productRequests).toEqual([]);
  wrapper.unmount();
});

it("drops a late Agent history page after an account switch", async () => {
  const wrapper = mountView();
  await flushPromises();
  let resolveOld: (value: unknown) => void = () => {};
  listApprovals.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
  const vm = wrapper.vm as unknown as {
    loadAgentHistory: () => Promise<void>;
    approvals: Array<Record<string, unknown>>;
  };
  const oldLoad = vm.loadAgentHistory();
  listApprovals.mockResolvedValueOnce({ approvals: [{ approval_id: "bob_history", status: "approved" }], total: 1 });
  listProductApprovalRequests.mockResolvedValueOnce({
    schema_version: "byq-product-approval-request-list.v1",
    requests: [],
    total: 0,
    pending_count: 0,
    attention_count: 0,
    limit: 20,
    offset: 0,
  });
  useAuthStore().setUser({ subject: "bob", workspace: { workspace_id: "workspace-bob" } } as any);
  await flushPromises();
  resolveOld({ approvals: [{ approval_id: "alice_history", status: "approved" }], total: 1 });
  await oldLoad;

  expect(vm.approvals.map(item => item.approval_id)).toEqual(["bob_history"]);
  wrapper.unmount();
});
