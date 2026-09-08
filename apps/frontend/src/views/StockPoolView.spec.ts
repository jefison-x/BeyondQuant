import { mount, flushPromises } from "@vue/test-utils";
import { createPinia } from "pinia";
import { nextTick } from "vue";
import { describe, expect, it, vi } from "vitest";
import ElementPlus, { ElMessage } from "element-plus";
import StockPoolView from "./StockPoolView.vue";
import { createIndexStockPool, refreshIndexStockPool } from "@/api/paper";

vi.mock("vue-router", () => ({ useRoute: () => ({ query: {}, path: "/stock-pools" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), onBeforeRouteLeave: vi.fn() }));
vi.mock("element-plus", async (load) => ({ ...await load<typeof import("element-plus")>(),
  ElMessage: { warning: vi.fn(), error: vi.fn(), success: vi.fn() } }));
vi.mock("@/api/paper", async (load) => ({ ...await load<typeof import("@/api/paper")>(),
  listStockPools: vi.fn(async () => ({ pools: [] })),
  listIndexPoolCatalog: vi.fn(async () => ({ indices: [{ index_symbol: "000300.SH", selectable: true }] })),
  createIndexStockPool: vi.fn(async () => ({ pool: { pool_id: "synthetic-index", pool_type: "index" } })),
  refreshIndexStockPool: vi.fn(),
}));

type State = { poolType: string; indexSymbol: string; indexTrackingMode: string; requestedAsOf: string;
  selected: unknown; producer: unknown; isHistoricalIndex: boolean; canRefreshPool: boolean;
  submit: () => Promise<void>; refreshIndexPool: () => Promise<void> };

async function setup() {
  vi.clearAllMocks();
  const wrapper = mount(StockPoolView, { global: { plugins: [createPinia(), ElementPlus],
    stubs: { ManagementWorkspace: true }, directives: { loading: () => {} } } });
  await flushPromises();
  return { wrapper, state: wrapper.vm as unknown as State };
}

describe("index pool tracking mode", () => {
  it("requires an explicit historical date before sending a request", async () => {
    const { wrapper, state } = await setup();
    state.poolType = "index"; state.indexTrackingMode = "historical_snapshot"; state.indexSymbol = "000300.SH";
    await state.submit();
    expect(createIndexStockPool).not.toHaveBeenCalled();
    expect(ElMessage.warning).toHaveBeenCalledWith("固定历史快照必须选择截至日期");
    state.requestedAsOf = "2024-06-28";
    await state.submit();
    expect(createIndexStockPool).toHaveBeenCalledWith(expect.objectContaining({
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
});
