import { createPinia, setActivePinia } from "pinia";
import { flushPromises, shallowMount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ElementPlus from "element-plus";
import StrategyView from "./StrategyView.vue";
import { useAuthStore } from "@/stores/auth";

const replaceRoute = vi.fn();
vi.mock("vue-router", () => ({
  useRoute: () => ({ path: "/strategy", query: {} }),
  useRouter: () => ({ replace: replaceRoute, push: vi.fn() }),
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
const listTasks = vi.fn();
const listArtifacts = vi.fn();
const getResearchEntity = vi.fn();
const getStrategyBacktestCount = vi.fn();
const getStrategyVersions = vi.fn();
const saveStrategyDraft = vi.fn();
const deleteStrategyDraft = vi.fn();
const approveStrategyVersion = vi.fn();

vi.mock("@/api/quant", () => ({
  approveStrategyVersion: (...args: unknown[]) => approveStrategyVersion(...args),
  listStrategies: (...args: unknown[]) => listStrategies(...args),
  createStrategyVersion: vi.fn(),
  deleteStrategyDraft: (...args: unknown[]) => deleteStrategyDraft(...args),
  exportStrategyVersion: vi.fn(),
  getResearchEntity: (...args: unknown[]) => getResearchEntity(...args),
  getStrategyBacktestCount: (...args: unknown[]) => getStrategyBacktestCount(...args),
  getStrategyVersions: (...args: unknown[]) => getStrategyVersions(...args),
  saveStrategyDraft: (...args: unknown[]) => saveStrategyDraft(...args),
  validateStrategy: vi.fn(),
}));

vi.mock("@/api/research", () => ({
  listTasks: (...args: unknown[]) => listTasks(...args),
  listArtifacts: (...args: unknown[]) => listArtifacts(...args),
}));

describe("StrategyView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    useAuthStore().token = "strategy-test";
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
    listTasks.mockResolvedValue({ tasks: [] });
    listArtifacts.mockResolvedValue({ artifacts: [] });
    getResearchEntity.mockReset();
    getResearchEntity.mockResolvedValue({});
    getStrategyBacktestCount.mockReset();
    getStrategyBacktestCount.mockResolvedValue({ backtest_count: 0, version_count: 0 });
    getStrategyVersions.mockReset();
    getStrategyVersions.mockResolvedValue({ versions: [] });
    saveStrategyDraft.mockReset();
    deleteStrategyDraft.mockReset();
    approveStrategyVersion.mockReset();
    replaceRoute.mockReset();
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

    expect(getStrategyVersions).toHaveBeenCalledWith("MomentumStrategy", "strategy-test");
    expect(getStrategyBacktestCount).toHaveBeenCalledWith("MomentumStrategy", "strategy-test");
    expect((wrapper.vm as unknown as { isReadonly: boolean }).isReadonly).toBe(true);
    expect((wrapper.vm as unknown as { backtestCount: number }).backtestCount).toBe(7);
    expect((wrapper.vm as unknown as { versionCount: number }).versionCount).toBe(3);
  });

  it("saves and soft-deletes a selected draft through Product API", async () => {
    const draft = {
      artifact_id: "artifact_draft",
      kind: "strategy_draft",
      status: "draft",
      content: { snapshot: { strategy_id: "DraftStrategy", script: "class CustomStrategy: pass" } },
    };
    listStrategies.mockResolvedValue({ strategies: [draft], total: 1, limit: 50, offset: 0 });
    listTasks.mockResolvedValue({ tasks: [{ task_id: "task_1" }] });
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
});
