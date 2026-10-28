import { flushPromises, shallowMount } from "@vue/test-utils";
import { beforeEach, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import ProductApprovalRequestPanel from "./ProductApprovalRequestPanel.vue";
import { useAuthStore } from "@/stores/auth";

const { listRequests, reconcileRequest, decideOnce, prompt, success, warning } = vi.hoisted(() => ({
  listRequests: vi.fn(), reconcileRequest: vi.fn(), decideOnce: vi.fn(), prompt: vi.fn(),
  success: vi.fn(), warning: vi.fn(),
}));

vi.mock("@/api/research", () => ({
  listProductApprovalRequests: (...args: unknown[]) => listRequests(...args),
  reconcileProductApprovalRequest: (...args: unknown[]) => reconcileRequest(...args),
}));
vi.mock("@/api/approvalRequestSubmissions", () => ({
  decideProductApprovalRequestOnce: (...args: unknown[]) => decideOnce(...args),
}));
vi.mock("element-plus", () => ({
  ElMessage: { success, warning },
  ElMessageBox: { prompt: (...args: unknown[]) => prompt(...args) },
}));

const requestId = `approval_request_${"1".repeat(32)}`;
const taskId = `task_${"2".repeat(32)}`;
const artifactId = `artifact_${"a".repeat(32)}`;
const pending = (owner = "alice", workspace = "workspace-alice") => ({
  request_id: requestId,
  request_type: "strategy_version" as const,
  status: "pending" as const,
  owner_principal: owner,
  workspace_id: workspace,
  task_id: taskId,
  resource_artifact_id: artifactId,
  content_sha256: "b".repeat(64),
  request_key: owner === "alice" ? "00000000-0000-4000-8000-000000000001" : "00000000-0000-4000-8000-000000000002",
  created_at: "2026-10-14T00:00:00Z",
  updated_at: "2026-10-14T00:00:00Z",
  strategy_version_artifact_id: artifactId,
});
const unresolved = (owner = "alice", workspace = "workspace-alice") => ({
  ...pending(owner, workspace), status: "outcome_unknown" as const,
  decision: "approved" as const, decision_key: owner === "alice"
    ? "00000000-0000-4000-8000-000000000003" : "00000000-0000-4000-8000-000000000004",
});

function emptyList() {
  return { schema_version: "byq-product-approval-request-list.v1", requests: [], total: 0,
    pending_count: 0, attention_count: 0, limit: 10, offset: 0 };
}

beforeEach(() => {
  vi.resetAllMocks();
  setActivePinia(createPinia());
  useAuthStore().setUser({ subject: "alice", workspace: { workspace_id: "workspace-alice" } } as any);
  listRequests.mockImplementation(({ status }: { status: string }) => Promise.resolve({
    ...emptyList(),
    requests: status === "pending" ? [pending()] : status === "unresolved" ? [unresolved()] : [],
    total: status === "pending" || status === "unresolved" ? 1 : 0,
    pending_count: 1,
    attention_count: status === "unresolved" ? 1 : 0,
  }));
  prompt.mockResolvedValue({ value: "审阅确认" });
});

it("does not apply an Alice decision result after switching to Bob's scope", async () => {
  let resolveDecision: (value: unknown) => void = () => {};
  decideOnce.mockImplementationOnce(() => new Promise(resolve => { resolveDecision = resolve; }));
  const changed = vi.spyOn(window, "dispatchEvent");
  const wrapper = shallowMount(ProductApprovalRequestPanel);
  await flushPromises();
  const vm = wrapper.vm as unknown as {
    pendingRequests: Array<Record<string, unknown>>;
    decide: (request: Record<string, unknown>, decision: "approved" | "rejected") => Promise<void>;
  };
  const aliceRequest = vm.pendingRequests[0];
  const decision = vm.decide(aliceRequest, "approved");
  await flushPromises();
  expect(decideOnce).toHaveBeenCalledOnce();

  listRequests.mockImplementation(({ status }: { status: string }) => Promise.resolve(emptyList()));
  useAuthStore().setUser({ subject: "bob", workspace: { workspace_id: "workspace-bob" } } as any);
  await flushPromises();
  resolveDecision({ request: { ...pending(), status: "approved", decision: "approved" } });
  await decision;
  await flushPromises();

  expect(vm.pendingRequests).toEqual([]);
  expect(changed.mock.calls.map(([event]) => (event as Event).type)).not.toContain("byq:approvals-changed");
  expect(success).not.toHaveBeenCalled();
  wrapper.unmount();
  changed.mockRestore();
});

it("does not apply a late unknown-outcome reconciliation after a scope switch", async () => {
  let resolveReconciliation: (value: unknown) => void = () => {};
  reconcileRequest.mockImplementationOnce(() => new Promise(resolve => { resolveReconciliation = resolve; }));
  const changed = vi.spyOn(window, "dispatchEvent");
  const wrapper = shallowMount(ProductApprovalRequestPanel);
  await flushPromises();
  const vm = wrapper.vm as unknown as {
    unresolvedRequests: Array<Record<string, unknown>>;
    reconcile: (id: string) => Promise<void>;
  };
  const reconciliation = vm.reconcile(requestId);
  await flushPromises();
  expect(reconcileRequest).toHaveBeenCalledWith(requestId);

  listRequests.mockImplementation(({ status }: { status: string }) => Promise.resolve(emptyList()));
  useAuthStore().setUser({ subject: "bob", workspace: { workspace_id: "workspace-bob" } } as any);
  await flushPromises();
  resolveReconciliation({ schema_version: "byq-product-approval-request.v1", request: {
    ...pending(), status: "approved", decision: "approved", decision_key: "00000000-0000-4000-8000-000000000003",
    observed_state: "confirmed",
  } });
  await reconciliation;
  await flushPromises();

  expect(vm.unresolvedRequests).toEqual([]);
  expect(decideOnce).not.toHaveBeenCalled();
  expect(changed.mock.calls.map(([event]) => (event as Event).type)).not.toContain("byq:approvals-changed");
  expect(success).not.toHaveBeenCalled();
  expect(warning).not.toHaveBeenCalled();
  wrapper.unmount();
  changed.mockRestore();
});
