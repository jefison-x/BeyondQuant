import { mount, flushPromises } from "@vue/test-utils";
import { useAuthStore } from "@/stores/auth";
import { createPinia } from "pinia";
import { nextTick } from "vue";
import { describe, expect, it, vi } from "vitest";
import ElementPlus, { ElMessage } from "element-plus";
import StockPoolView from "./StockPoolView.vue";
import { submitPoolCreation, refreshIndexStockPool, replaceStockPoolSnapshot } from "@/api/paper";
import { listSecurities } from "@/api/dataCenter";

const routerHarness = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock("vue-router", () => ({ useRoute: () => ({ query: {}, path: "/stock-pools" }),
  useRouter: () => routerHarness, onBeforeRouteLeave: vi.fn() }));
vi.mock("element-plus", async (load) => ({ ...await load<typeof import("element-plus")>(),
  ElMessage: { warning: vi.fn(), error: vi.fn(), success: vi.fn() } }));
vi.mock("@/api/paper", async (load) => ({ ...await load<typeof import("@/api/paper")>(),
  listStockPools: vi.fn(async () => ({ pools: [] })),
  getStockPool: vi.fn(async () => ({ pool: { pool_id: "pool_exact", name: "银行池", pool_type: "custom", current_snapshot_id: "snapshot_saved", metadata_version: 1, snapshot: { definition: {} } } })),
  listStockPoolSnapshots: vi.fn(async () => ({ snapshots: [] })),
  listStockPoolReferences: vi.fn(async () => ({ references: [] })),
  getStockPoolReadiness: vi.fn(async () => ({ readiness: {} })),
  listIndexPoolCatalog: vi.fn(async () => ({ indices: [{ index_symbol: "000300.SH", selectable: true }] })),
  submitPoolCreation: vi.fn(async () => ({ pool: { pool_id: "synthetic-index", pool_type: "index" } })),
  refreshIndexStockPool: vi.fn(),
  replaceStockPoolSnapshot: vi.fn(),
}));
vi.mock("@/api/dataCenter", async (load) => ({ ...await load<typeof import("@/api/dataCenter")>(), listSecurities: vi.fn() }));

type State = { poolType: string; indexSymbol: string; indexTrackingMode: string; requestedAsOf: string;
  selected: unknown; producer: unknown; isHistoricalIndex: boolean; canRefreshPool: boolean;
  createMembers: Array<{ symbol: string; name: string; weightPercent: number | null }>;
  editMembers: Array<{ symbol: string; name: string; weightPercent: number | null }>;
  setCreateEqualWeights: () => void; clearCreateWeights: () => void;
  setEditEqualWeights: () => void; clearEditWeights: () => void;
  saveSnapshot: () => Promise<void>;
  searchSecurities: (query: string) => Promise<void>; syncCreateMembers: (symbols?: string[]) => void;
  formatPoolWeight: (weight: unknown) => string;
  manualCodeAllowed: boolean;
  sendStockPoolToAgent: () => void;
  submit: () => Promise<void>; refreshIndexPool: () => Promise<void> };

async function setup() {
  vi.clearAllMocks();
  localStorage.clear();
  const pinia = createPinia();
  useAuthStore(pinia).setUser({subject:"alice", workspace:{workspace_id:"workspace_alice"}} as any);
  const wrapper = mount(StockPoolView, { global: { plugins: [pinia, ElementPlus],
    stubs: { ManagementWorkspace: true }, directives: { loading: () => {} } } });
  await flushPromises();
  return { wrapper, state: wrapper.vm as unknown as State };
}

describe("index pool tracking mode", () => {
  it("requires an explicit historical date before sending a request", async () => {
    const { wrapper, state } = await setup();
    state.poolType = "index"; state.indexTrackingMode = "historical_snapshot"; state.indexSymbol = "000300.SH";
    await state.submit();
    expect(submitPoolCreation).not.toHaveBeenCalled();
    expect(ElMessage.warning).toHaveBeenCalledWith("固定历史快照必须选择截至日期");
    state.requestedAsOf = "2024-06-28";
    await state.submit();
    expect(submitPoolCreation).toHaveBeenCalledWith("index", expect.objectContaining({
      tracking_mode: "historical_snapshot", requested_as_of: "20240628", index_symbol: "000300.SH",
    }), expect.any(String));
    expect(state.indexTrackingMode).toBe("follow_index");
    wrapper.unmount();
  });

  it("does not offer or send refresh for historical or unverified definitions", async () => {
    const { wrapper, state } = await setup();
    state.selected = { pool_id: "original", pool_type: "index" };
    state.producer = { pool_id: "foreign", definition: {} };
    await nextTick();
    expect(state.canRefreshPool).toBe(false);
    await state.refreshIndexPool();
    state.producer = { pool_id: "original", definition: { tracking_mode: "historical_snapshot" } };
    await nextTick();
    expect(state.isHistoricalIndex).toBe(true);
    expect(state.canRefreshPool).toBe(false);
    await state.refreshIndexPool();
    expect(refreshIndexStockPool).not.toHaveBeenCalled();
    state.producer = { pool_id: "original", definition: {} };
    await nextTick();
    expect(state.canRefreshPool).toBe(true);
    wrapper.unmount();
  });

  it("uses directory search when available and keeps a validated code fallback when it has no match", async () => {
    const { wrapper, state } = await setup();
    vi.mocked(listSecurities).mockResolvedValue({ securities: [], total: 0, limit: 30, offset: 0, snapshot: null });
    state.poolType = "custom";
    (wrapper.vm as any).name = "测试股票池";
    await state.searchSecurities("招商银行");
    state.syncCreateMembers(["招商银行"]);
    expect(state.manualCodeAllowed).toBe(false);
    expect(state.createMembers).toEqual([]);

    await state.searchSecurities("600036.SH");
    expect(state.manualCodeAllowed).toBe(true);
    state.syncCreateMembers(["600036.SH"]);
    expect(state.createMembers[0]).toMatchObject({ symbol: "600036.SH", name: "", weightPercent: null });
    state.createMembers[0].weightPercent = 100;
    expect(state.formatPoolWeight(null)).toBe("未设置");
    expect(state.formatPoolWeight("0.6")).toBe("60.00%");

    await state.submit();
    expect(listSecurities).toHaveBeenCalledWith({ query: "招商银行", limit: 30 });
    expect(submitPoolCreation).toHaveBeenCalledWith("custom", expect.objectContaining({
      symbols: ["600036.SH"], weights: { "600036.SH": 1 },
    }), expect.any(String));
    wrapper.unmount();
  });

  it.each([[null, 40], [0, 100], [60, 20], [Number.NaN, 100]])(
    "keeps invalid weights %s/%s in the form without create or snapshot requests", async (first, second) => {
      const { wrapper, state } = await setup();
      (wrapper.vm as any).name = "保留输入";
      const rows = [{ symbol: "600036.SH", name: "招商银行", weightPercent: first },
        { symbol: "601398.SH", name: "工商银行", weightPercent: second }];
      state.createMembers = rows;
      await state.submit();
      state.selected = { pool_id: "pool_exact", current_snapshot_id: "snapshot_exact" };
      state.editMembers = rows;
      await state.saveSnapshot();
      expect(submitPoolCreation).not.toHaveBeenCalled();
      expect(replaceStockPoolSnapshot).not.toHaveBeenCalled();
      expect(state.createMembers).toEqual(rows);
      expect(ElMessage.error).toHaveBeenCalledWith(expect.stringContaining("权重"));
      wrapper.unmount();
    });

  it("submits precise decimal fractions without binary division noise", async () => {
    const { wrapper, state } = await setup();
    (wrapper.vm as any).name = "小数权重";
    state.createMembers = [{ symbol: "600036.SH", name: "招商银行", weightPercent: 20.01 },
      { symbol: "601398.SH", name: "工商银行", weightPercent: 79.99 }];
    await state.submit();
    expect(submitPoolCreation).toHaveBeenCalledWith("custom", expect.objectContaining({
      weights: { "600036.SH": 0.2001, "601398.SH": 0.7999 },
    }), expect.any(String));
    wrapper.unmount();
  });

  it("sets three members to exact 100.00% equal weights and only saves on submit", async () => {
    const { wrapper, state } = await setup();
    (wrapper.vm as any).showCreate = true;
    (wrapper.vm as any).name = "三只股票";
    state.createMembers = [
      { symbol: "600036.SH", name: "招商银行", weightPercent: null },
      { symbol: "601398.SH", name: "工商银行", weightPercent: null },
      { symbol: "000001.SZ", name: "平安银行", weightPercent: null },
    ];
    await nextTick();
    await wrapper.get('[data-testid="stock-pool-create-equal-weights"]').trigger("click");
    expect(state.createMembers.map(({ weightPercent }) => weightPercent)).toEqual([33.34, 33.33, 33.33]);
    expect(submitPoolCreation).not.toHaveBeenCalled();

    await wrapper.get('[data-testid="stock-pool-create-clear-weights"]').trigger("click");
    expect(state.createMembers.every(({ weightPercent }) => weightPercent === null)).toBe(true);
    expect(submitPoolCreation).not.toHaveBeenCalled();
    state.setCreateEqualWeights();
    await state.submit();
    expect(submitPoolCreation).toHaveBeenCalledWith("custom", expect.objectContaining({
      weights: { "600036.SH": 0.3334, "601398.SH": 0.3333, "000001.SZ": 0.3333 },
    }), expect.any(String));
    wrapper.unmount();
  });

  it("distributes seven-member remainder in 0.01% steps and preserves weights when membership changes", async () => {
    const { wrapper, state } = await setup();
    state.editMembers = Array.from({ length: 7 }, (_, index) => ({
      symbol: `60000${index}.SH`, name: `股票${index}`, weightPercent: null,
    }));
    state.setEditEqualWeights();
    expect(state.editMembers.map(({ weightPercent }) => weightPercent)).toEqual([
      14.29, 14.29, 14.29, 14.29, 14.28, 14.28, 14.28,
    ]);
    expect(state.editMembers.reduce((sum, { weightPercent }) => sum + (weightPercent ?? 0), 0)).toBe(100);
    state.syncCreateMembers(["600036.SH", "601398.SH", "000001.SZ"]);
    state.createMembers = [
      { symbol: "600036.SH", name: "招商银行", weightPercent: 60 },
      { symbol: "601398.SH", name: "工商银行", weightPercent: 40 },
    ];
    state.syncCreateMembers(["600036.SH", "601398.SH", "000001.SZ"]);
    expect(state.createMembers.map(({ weightPercent }) => weightPercent)).toEqual([60, 40, null]);
    expect(replaceStockPoolSnapshot).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("applies edit equal weights as a draft until the member snapshot is saved", async () => {
    const { wrapper, state } = await setup();
    state.selected = { pool_id: "pool_exact", current_snapshot_id: "snapshot_exact", pool_type: "custom" };
    state.editMembers = [
      { symbol: "600036.SH", name: "招商银行", weightPercent: 80 },
      { symbol: "601398.SH", name: "工商银行", weightPercent: 20 },
    ];
    await nextTick();
    state.setEditEqualWeights();
    expect(state.editMembers.map(({ weightPercent }) => weightPercent)).toEqual([50, 50]);
    expect(replaceStockPoolSnapshot).not.toHaveBeenCalled();
    state.clearEditWeights();
    expect(state.editMembers.every(({ weightPercent }) => weightPercent === null)).toBe(true);
    expect(replaceStockPoolSnapshot).not.toHaveBeenCalled();
    state.setEditEqualWeights();
    await state.saveSnapshot();
    expect(replaceStockPoolSnapshot).toHaveBeenCalledWith("pool_exact", expect.objectContaining({
      expected_current_snapshot_id: "snapshot_exact",
      symbols: ["600036.SH", "601398.SH"],
      weights: { "600036.SH": 0.5, "601398.SH": 0.5 },
    }), expect.any(String));
    wrapper.unmount();
  });

  it("opens a new Agent draft with the exact pool and current member-version IDs", async () => {
    const { wrapper, state } = await setup();
    state.selected = { pool_id: "pool_exact", name: "银行观察池", current_snapshot_id: "snapshot_exact" };
    state.sendStockPoolToAgent();
    expect(routerHarness.push).toHaveBeenCalledWith(expect.objectContaining({
      path: "/agent",
      query: expect.objectContaining({
        new: expect.any(String),
        context: "stock-pool",
        draft: expect.stringContaining("股票池 ID：pool_exact；成员名单版本 ID：snapshot_exact"),
      }),
    }));
    wrapper.unmount();
  });
});
