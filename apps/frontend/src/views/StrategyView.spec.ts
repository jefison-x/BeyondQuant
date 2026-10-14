import { createPinia, setActivePinia } from "pinia";
import { flushPromises, shallowMount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ElementPlus, { ElMessageBox } from "element-plus";
import StrategyView from "./StrategyView.vue";
import { useAuthStore } from "@/stores/auth";

const replaceRoute = vi.fn();
const pushRoute = vi.fn();
vi.mock("vue-router", () => ({
  useRoute: () => ({ path: "/strategy", query: {} }),
  useRouter: () => ({ replace: replaceRoute, push: pushRoute }),
  onBeforeRouteLeave: vi.fn(),
}));

function mountView() {
  return shallowMount(StrategyView, {
    global: {
      plugins: [ElementPlus],
      stubs: {
        AppStateBlock: { template: "<div><slot /></div>" },
      },
    },
  });
}

const listStrategies = vi.fn();
const listTaskOptions = vi.fn();
const getResearchEntity = vi.fn();
const getStrategyVersionApproval = vi.fn();
const getStrategyBacktestCount = vi.fn();
const getStrategyVersions = vi.fn();
const saveStrategyDraft = vi.fn();
const deleteStrategyDraft = vi.fn();
const submitProductApprovalRequestOnce = vi.fn();

vi.mock("@/api/quant", () => ({
  listStrategies: (...args: unknown[]) => listStrategies(...args),
  createStrategyVersion: vi.fn(),
  deleteStrategyDraft: (...args: unknown[]) => deleteStrategyDraft(...args),
  exportStrategyVersion: vi.fn(),
  getResearchEntity: (...args: unknown[]) => getResearchEntity(...args),
  getStrategyBacktestCount: (...args: unknown[]) => getStrategyBacktestCount(...args),
  getStrategyVersionApproval: (...args: unknown[]) => getStrategyVersionApproval(...args),
  getStrategyVersions: (...args: unknown[]) => getStrategyVersions(...args),
  saveStrategyDraft: (...args: unknown[]) => saveStrategyDraft(...args),
  validateStrategy: vi.fn(),
}));

vi.mock("@/api/research", () => ({
  listTaskOptions: (...args: unknown[]) => listTaskOptions(...args),
}));

vi.mock("@/api/approvalRequestSubmissions", () => ({
  submitProductApprovalRequestOnce: (...args: unknown[]) => submitProductApprovalRequestOnce(...args),
}));

describe("StrategyView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    useAuthStore().token = "strategy-test";
    useAuthStore().setUser({ subject: "alice", workspace: { workspace_id: "workspace-alice" } } as any);
    listStrategies.mockReset();
    listStrategies.mockImplementation((_token: string, options: { lifecycle: string }) =>
      Promise.resolve({
        strategies: options.lifecycle === "superseded"
          ? [{ artifact_id: "artifact_archived", kind: "strategy_draft", status: "superseded", content: { snapshot: { strategy_id: "Archived" } } }]
          : [],
        total: options.lifecycle === "superseded" ? 1 : 0,
        limit: 50,
        offset: 0,
      }),
    );
    listTaskOptions.mockResolvedValue({ tasks: [] });
    getStrategyVersionApproval.mockReset();
    getStrategyVersionApproval.mockResolvedValue({ approval: null });
    getResearchEntity.mockReset();
    getResearchEntity.mockResolvedValue({});
    getStrategyBacktestCount.mockReset();
    getStrategyBacktestCount.mockResolvedValue({ backtest_count: 0, version_count: 0 });
    getStrategyVersions.mockReset();
    getStrategyVersions.mockResolvedValue({ versions: [] });
    saveStrategyDraft.mockReset();
    deleteStrategyDraft.mockReset();
    submitProductApprovalRequestOnce.mockReset();
    replaceRoute.mockReset();
    pushRoute.mockReset();
    vi.spyOn(ElMessageBox, "confirm").mockResolvedValue("confirm" as never);
  });

  it("hides superseded drafts by default and can open the explicit archive view", async () => {
    const wrapper = mountView();
    await flushPromises();
    expect(listStrategies).toHaveBeenCalledWith(
      "strategy-test",
      expect.objectContaining({ lifecycle: "active", limit: 50, offset: 0 }),
    );
    await (wrapper.vm as unknown as { changeLifecycle: (value: "superseded") => Promise<void> })
      .changeLifecycle("superseded");
    await flushPromises();
    expect(listStrategies).toHaveBeenLastCalledWith(
      "strategy-test",
      expect.objectContaining({ lifecycle: "superseded" }),
    );
    expect((wrapper.vm as unknown as { artifacts: Array<{ artifact_id: string }> }).artifacts[0].artifact_id)
      .toBe("artifact_archived");
  });

  it("loads the exact paginated total from Product API", async () => {
    listStrategies.mockResolvedValue({ strategies: [], total: 120, limit: 50, offset: 0 });
    const wrapper = mountView();
    await flushPromises();
    expect((wrapper.vm as unknown as { total: number; page: number }).total).toBe(120);
    expect((wrapper.vm as unknown as { total: number; page: number }).page).toBe(1);
  });

  it("loads immutable version history, read-only state, and exact backtest stats", async () => {
    const version = {
      artifact_id: "artifact_version",
      kind: "strategy_version",
      status: "validated",
      content: { snapshot: { strategy_id: "MomentumStrategy", script: "class CustomStrategy: pass" } },
    };
    listStrategies.mockResolvedValue({ strategies: [version], total: 1, limit: 50, offset: 0 });
    getResearchEntity.mockResolvedValue(version);
    getStrategyVersions.mockResolvedValue({ versions: [{ artifact_id: "artifact_version", version_id: "v1" }] });
    getStrategyBacktestCount.mockResolvedValue({ backtest_count: 7, version_count: 3 });
    const wrapper = mountView();
    await flushPromises();

    expect(getStrategyVersions).toHaveBeenCalledWith("MomentumStrategy", "strategy-test", { limit: 50, offset: 0 });
    expect(getStrategyBacktestCount).toHaveBeenCalledWith("MomentumStrategy", "strategy-test");
    expect((wrapper.vm as unknown as { isReadonly: boolean }).isReadonly).toBe(true);
    expect((wrapper.vm as unknown as { backtestCount: number }).backtestCount).toBe(7);
    expect((wrapper.vm as unknown as { versionCount: number }).versionCount).toBe(3);
    const vm = wrapper.vm as unknown as {
      refreshStrategyMeta: (page: number) => Promise<void>;
      historyPage: number; historyTotal: number; versionHistory: Array<{ artifact_id: string }>;
    };
    let first!: (value: Record<string, unknown>) => void;
    let second!: (value: Record<string, unknown>) => void;
    getStrategyVersions.mockImplementationOnce(() => new Promise(resolve => { first = resolve; }));
    getStrategyVersions.mockImplementationOnce(() => new Promise(resolve => { second = resolve; }));
    const oldPage = vm.refreshStrategyMeta(2);
    const newPage = vm.refreshStrategyMeta(3);
    second({ versions: [{ artifact_id: "page-three" }], total: 1005 });
    await newPage;
    first({ versions: [{ artifact_id: "page-two" }], total: 1005 });
    await oldPage;
    expect(getStrategyVersions).toHaveBeenLastCalledWith("MomentumStrategy", "strategy-test", { limit: 50, offset: 100 });
    expect(vm.historyPage).toBe(3);
    expect(vm.historyTotal).toBe(1005);
    expect(vm.versionHistory[0].artifact_id).toBe("page-three");

  });

  it("opens a fresh editable strategy from the explicit create action", async () => {
    const version = {
      artifact_id: "artifact_version",
      kind: "strategy_version",
      status: "validated",
      content: { snapshot: { strategy_id: "ExistingStrategy", script: "class CustomStrategy: pass" } },
    };
    listStrategies.mockResolvedValue({ strategies: [version], total: 1, limit: 50, offset: 0 });
    const wrapper = mountView();
    await flushPromises();
    expect((wrapper.vm as unknown as { isReadonly: boolean }).isReadonly).toBe(true);

    await (wrapper.vm as unknown as { newDraft: () => Promise<void> }).newDraft();

    const state = wrapper.vm as unknown as {
      isReadonly: boolean;
      selected: Record<string, unknown> | null;
      strategyId: string;
      strategyName: string;
      script: string;
      filter: string;
    };
    expect(state.isReadonly).toBe(false);
    expect(state.selected).toBeNull();
    expect(state.strategyId).toBe("CustomStrategy");
    expect(state.strategyName).toBe("自定义策略");
    expect(state.script).toBe("");
    expect(state.filter).toBe("draft");
    expect(replaceRoute).toHaveBeenCalledWith({ path: "/strategy", query: {} });
  });

  it("saves and soft-deletes a selected draft through Product API", async () => {
    const draft = {
      artifact_id: "artifact_draft",
      kind: "strategy_draft",
      status: "draft",
      content: { snapshot: { strategy_id: "DraftStrategy", script: "class CustomStrategy: pass" } },
    };
    listStrategies.mockResolvedValue({ strategies: [draft], total: 1, limit: 50, offset: 0 });
    listTaskOptions.mockResolvedValue({ tasks: [{ task_id: "task_1" }] });
    saveStrategyDraft.mockResolvedValue({ artifact: { artifact_id: "artifact_draft" } });
    deleteStrategyDraft.mockResolvedValue({ artifact: { artifact_id: "artifact_draft", status: "superseded" } });
    const wrapper = mountView();
    await flushPromises();
    await (wrapper.vm as unknown as { select: (row: Record<string, unknown>) => Promise<void> }).select(draft);
    await (wrapper.vm as unknown as { saveDraft: () => Promise<void> }).saveDraft();
    expect(saveStrategyDraft).toHaveBeenCalledWith(
      expect.objectContaining({ task_id: "task_1" }),
      "strategy-test",
    );
    await (wrapper.vm as unknown as { removeDraft: () => Promise<void> }).removeDraft();
    expect(deleteStrategyDraft).toHaveBeenCalledWith("artifact_draft", "strategy-test");
  });

  it("submits a typed approval request and does not start a backtest when approval is missing", async () => {
    const taskId = `task_${"1".repeat(32)}`;
    const artifactId = `artifact_${"a".repeat(32)}`;
    const version = {
      artifact_id: artifactId, task_id: taskId, kind: "strategy_version", status: "validated",
      content: { snapshot: { strategy_id: "MomentumStrategy", script: "class CustomStrategy: pass" } },
    };
    listStrategies.mockResolvedValue({ strategies: [version], total: 1, limit: 50, offset: 0 });
    getResearchEntity.mockResolvedValue(version);
    submitProductApprovalRequestOnce.mockResolvedValue({
      reconciled: false,
      request: {
        request_id: `approval_request_${"1".repeat(32)}`, request_type: "strategy_version", status: "pending",
        owner_principal: "alice", workspace_id: "workspace-alice", task_id: taskId,
        resource_artifact_id: artifactId, content_sha256: "b".repeat(64), request_key: "00000000-0000-4000-8000-000000000008",
        created_at: "2026-10-14T00:00:00Z", updated_at: "2026-10-14T00:00:00Z",
        strategy_version_artifact_id: artifactId,
      },
    });
    const wrapper = mountView();
    await flushPromises();

    await (wrapper.vm as unknown as { openBacktest: () => Promise<void> }).openBacktest();

    expect(submitProductApprovalRequestOnce).toHaveBeenCalledWith(
      { ownerPrincipal: "alice", workspaceId: "workspace-alice" },
      {
        schema_version: "byq-product-approval-request.v1",
        request_type: "strategy_version",
        task_id: taskId,
        strategy_version_artifact_id: artifactId,
      },
    );
    expect(pushRoute).not.toHaveBeenCalled();
  });

  it("starts a backtest only after a separately read approval authorizes execution", async () => {
    const version = {
      artifact_id: "artifact_version", task_id: "task_1", kind: "strategy_version", status: "validated",
      content: { snapshot: { strategy_id: "MomentumStrategy", script: "class CustomStrategy: pass" } },
    };
    listStrategies.mockResolvedValue({ strategies: [version], total: 1, limit: 50, offset: 0 });
    getResearchEntity.mockResolvedValue(version);
    getStrategyVersionApproval.mockResolvedValue({ approval: { content: { execution_authorized: true, decision: "approved" } } });
    const wrapper = mountView();
    await flushPromises();

    await (wrapper.vm as unknown as { openBacktest: () => Promise<void> }).openBacktest();

    expect(submitProductApprovalRequestOnce).not.toHaveBeenCalled();
    expect(pushRoute).toHaveBeenCalledWith({ path: "/backtest", query: { strategy: "artifact_version" } });
  });

  it("does not let a late approval read for one immutable version overwrite another selection", async () => {
    const artifactA = `artifact_${"a".repeat(32)}`;
    const artifactB = `artifact_${"b".repeat(32)}`;
    const versionA = { artifact_id: artifactA, task_id: `task_${"1".repeat(32)}`, kind: "strategy_version", status: "validated",
      content: { snapshot: { strategy_id: "VersionA", script: "class CustomStrategy: pass" } } };
    const versionB = { artifact_id: artifactB, task_id: `task_${"2".repeat(32)}`, kind: "strategy_version", status: "validated",
      content: { snapshot: { strategy_id: "VersionB", script: "class CustomStrategy: pass" } } };
    getResearchEntity.mockImplementation((_type: string, id: string) => Promise.resolve(id === artifactA ? versionA : versionB));
    let resolveApprovalA: (value: unknown) => void = () => {};
    getStrategyVersionApproval.mockImplementation((id: string) => id === artifactA
      ? new Promise(resolve => { resolveApprovalA = resolve; })
      : Promise.resolve({ approval: { content: { execution_authorized: true, source: "version-b" } } }));
    const wrapper = mountView();
    await flushPromises();
    const vm = wrapper.vm as unknown as {
      select: (row: Record<string, unknown>, updateRoute?: boolean) => Promise<void>;
      approvalArtifactId: string;
      approval: Record<string, unknown> | null;
    };
    const oldSelection = vm.select(versionA, false);
    await flushPromises();
    await vm.select(versionB, false);
    resolveApprovalA({ approval: { content: { execution_authorized: false, source: "version-a" } } });
    await oldSelection;

    expect(vm.approvalArtifactId).toBe(artifactB);
    expect(vm.approval).toEqual({ execution_authorized: true, source: "version-b" });
    wrapper.unmount();
  });

  it("does not submit a backtest request when selection changes during confirmation", async () => {
    const artifactA = `artifact_${"c".repeat(32)}`;
    const artifactB = `artifact_${"d".repeat(32)}`;
    const versionA = { artifact_id: artifactA, task_id: `task_${"3".repeat(32)}`, kind: "strategy_version", status: "validated",
      content: { snapshot: { strategy_id: "VersionA", script: "class CustomStrategy: pass" } } };
    const versionB = { artifact_id: artifactB, task_id: `task_${"4".repeat(32)}`, kind: "strategy_version", status: "validated",
      content: { snapshot: { strategy_id: "VersionB", script: "class CustomStrategy: pass" } } };
    getResearchEntity.mockImplementation((_type: string, id: string) => Promise.resolve(id === artifactA ? versionA : versionB));
    let resolveConfirmation: (value: string) => void = () => undefined;
    vi.mocked(ElMessageBox.confirm).mockImplementationOnce(() =>
      new Promise<string>(resolve => { resolveConfirmation = resolve; }) as never);
    const wrapper = mountView();
    await flushPromises();
    const vm = wrapper.vm as unknown as {
      select: (row: Record<string, unknown>, updateRoute?: boolean) => Promise<void>;
      openBacktest: () => Promise<void>;
    };
    await vm.select(versionA, false);
    const start = vm.openBacktest();
    await flushPromises();
    await vm.select(versionB, false);
    resolveConfirmation("confirm");
    await start;

    expect(submitProductApprovalRequestOnce).not.toHaveBeenCalled();
    expect(pushRoute).not.toHaveBeenCalled();
    wrapper.unmount();
  });
});
