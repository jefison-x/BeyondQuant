import { mount, flushPromises } from "@vue/test-utils";
import { useAuthStore } from "@/stores/auth";
import { createPinia } from "pinia";
import { nextTick } from "vue";
import { describe, expect, it, vi } from "vitest";
import ElementPlus, { ElMessage } from "element-plus";
import StockPoolView from "./StockPoolView.vue";
import { submitPoolCreation, refreshIndexStockPool, replaceStockPoolSnapshot, previewDynamicStockPool, updateDynamicStockPoolDefinition, getStockPool, getStockPoolProducer } from "@/api/paper";
import { listSecurities } from "@/api/dataCenter";
import type { DynamicStockPoolPreview, DynamicStockPoolRule } from "@/api/types";

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
  getStockPoolProducer: vi.fn(),
  listStockPoolMaterializations: vi.fn(async () => ({ runs: [], total: 0 })),
  listIndexPoolCatalog: vi.fn(async () => ({ indices: [{ index_symbol: "000300.SH", selectable: true }] })),
  submitPoolCreation: vi.fn(async () => ({ pool: { pool_id: "synthetic-index", pool_type: "index" } })),
  previewDynamicStockPool: vi.fn(async () => ({ schema_version: "dynamic-stock-pool-preview.v1", authoritative: false,
    requested_as_of: "20261116", effective_trade_date: "20261113", members: [], member_count: 0,
    rule_fingerprint: "preview-fingerprint", input_manifest: { base_universe: { row_count: 2 }, record_count: 2, selected_count: 0 } })),
  updateDynamicStockPoolDefinition: vi.fn(async (_poolId: string, payload: { rule: DynamicStockPoolRule; status: "draft" | "active" | "paused" }) => ({
    producer: { definition_id: "definition_dynamic", pool_id: "pool_dynamic", producer_kind: "dynamic",
      schema_version: "stock-pool-producer.v1", version: 5, status: payload.status, definition: payload.rule,
      schedule: {}, definition_fingerprint: "definition-fingerprint" },
  })),
  refreshIndexStockPool: vi.fn(),
  replaceStockPoolSnapshot: vi.fn(),
}));
vi.mock("@/api/dataCenter", async (load) => ({ ...await load<typeof import("@/api/dataCenter")>(), listSecurities: vi.fn() }));

type State = { poolType: string; indexSymbol: string; indexTrackingMode: string; requestedAsOf: string;
  selected: unknown; producer: unknown; isHistoricalIndex: boolean; canRefreshPool: boolean;
  name: string; dynamicIndustry: string; dynamicMinimumMarketCap: number | null; dynamicPeTtmMaximum: number | null;
  dynamicPbMaximum: number | null; dynamicDividendYieldMinimum: number | null; dynamicNetProfitYoyMinimum: number | null;
  dynamicTopN: number; dynamicRanking: string | null; dynamicDirection: "asc" | "desc";
  dynamicCadence: string; dynamicWeightMode: string; dynamicRuleText: string; dynamicRuleBaseline: string;
  dynamicRuleError: string; dynamicPreview: DynamicStockPoolPreview | null; dynamicDefinitionDirty: boolean; showCreate: boolean;
  createMembers: Array<{ symbol: string; name: string; weightPercent: number | null }>;
  editMembers: Array<{ symbol: string; name: string; weightPercent: number | null }>;
  setCreateEqualWeights: () => void; clearCreateWeights: () => void;
  setEditEqualWeights: () => void; clearEditWeights: () => void;
  saveSnapshot: () => Promise<void>;
  searchSecurities: (query: string) => Promise<void>; syncCreateMembers: (symbols?: string[]) => void;
  formatPoolWeight: (weight: unknown) => string;
  manualCodeAllowed: boolean;
  sendStockPoolToAgent: () => void;
  submit: () => Promise<void>; refreshIndexPool: () => Promise<void>; openCreate: () => void; closeCreate: () => void;
  previewDynamic: () => Promise<void>; saveDynamicDefinition: (status: "draft" | "active" | "paused") => Promise<void>;
  onDynamicRuleTextInput: (text: string) => void; loadDynamicRule: (rule: DynamicStockPoolRule, text?: string) => void;
  restoreDynamicEditorAfterCreateClose: () => void; select: (row: Record<string, unknown>, updateRoute?: boolean) => Promise<void> };

async function setup() {
  vi.clearAllMocks();
  localStorage.clear();
  const pinia = createPinia();
  useAuthStore(pinia).setUser({subject:"alice", workspace:{workspace_id:"workspace_alice"}} as any);
  const wrapper = mount(StockPoolView, { global: { plugins: [pinia, ElementPlus],
    stubs: { ManagementWorkspace: { template: "<div><slot name='actions' /><slot name='catalog' /><slot name='detail' /></div>" } },
    directives: { loading: () => {} } } });
  await flushPromises();
  return { wrapper, state: wrapper.vm as unknown as State };
}

function ruleDefinitionRecord(rule: DynamicStockPoolRule): Record<string, unknown> {
  return {
    schema_version: rule.schema_version,
    base_universe: rule.base_universe,
    filters: rule.filters,
    ranking: rule.ranking,
    top_n: rule.top_n,
    missing_policy: rule.missing_policy,
    weight_mode: rule.weight_mode,
    cadence: rule.cadence,
  };
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

describe("dynamic pool visual rule editor", () => {
  const baseRule: DynamicStockPoolRule = {
    schema_version: "dynamic-stock-pool-rule.v1",
    base_universe: { kind: "security_master" },
    filters: [
      { field: "security.exchange", operator: "in", value: ["SSE", "SZSE"] },
      { field: "daily_basic.pb", operator: "lte", value: 2.2 },
      { field: "daily_basic.pb", operator: "lte", value: 1.8 },
    ],
    ranking: { field: "daily_basic.pb", direction: "asc" },
    top_n: 25,
    missing_policy: "exclude",
    weight_mode: "unweighted",
    cadence: "weekly",
  };

  it("uses the same visible rule for preview and creation while preserving advanced filters", async () => {
    const { wrapper, state } = await setup();
    state.openCreate();
    state.poolType = "dynamic";
    state.name = "银行价值观察";
    state.requestedAsOf = "2026-11-16";
    await nextTick();

    expect(wrapper.find('[data-testid="dynamic-create-industry"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("万元");
    expect(wrapper.text()).toContain("按该日期可见的证券资料精确匹配");
    expect(wrapper.text()).toContain("字段缺失的股票都会被排除");
    expect((wrapper.get('[data-testid="dynamic-create-advanced"]').element as HTMLDetailsElement).open).toBe(false);

    state.onDynamicRuleTextInput(JSON.stringify(baseRule));
    state.dynamicIndustry = "银行";
    state.dynamicMinimumMarketCap = 100000;
    state.dynamicPeTtmMaximum = 12;
    state.dynamicPbMaximum = 1.1;
    state.dynamicDividendYieldMinimum = 3.5;
    state.dynamicNetProfitYoyMinimum = -5;
    await nextTick();

    await state.previewDynamic();
    expect(wrapper.text()).toContain("数据截至 2026-11-13");
    expect(wrapper.text()).toContain("输入证券 2 只 · 参与计算 2 只 · 符合 0 只");
    expect(wrapper.text()).toContain("本次预览不证明全市场覆盖");
    expect(wrapper.find('[data-testid="dynamic-advanced-condition-notice"]').exists()).toBe(true);
    await state.submit();

    const previewRule = vi.mocked(previewDynamicStockPool).mock.calls[0][0];
    const createPayload = vi.mocked(submitPoolCreation).mock.calls[0][1] as { rule: DynamicStockPoolRule; requested_as_of: string };
    expect(createPayload.requested_as_of).toBe("20261116");
    expect(createPayload.rule).toEqual(previewRule);
    expect(previewRule.filters).toEqual(expect.arrayContaining([
      { field: "security.exchange", operator: "in", value: ["SSE", "SZSE"] },
      { field: "daily_basic.pb", operator: "lte", value: 1.8 },
      { field: "security.industry", operator: "eq", value: "银行" },
      { field: "daily_basic.total_mv", operator: "gte", value: 100000 },
      { field: "daily_basic.pe_ttm", operator: "lte", value: 12 },
      { field: "daily_basic.pb", operator: "lte", value: 1.1 },
      { field: "daily_basic.dv_ttm", operator: "gte", value: 3.5 },
      { field: "financial.netprofit_yoy", operator: "gte", value: -5 },
    ]));
    expect(previewRule.ranking).toEqual({ field: "daily_basic.pb", direction: "asc" });
    expect(previewRule.top_n).toBe(25);
    expect(previewRule.cadence).toBe("weekly");
    expect(previewRule.weight_mode).toBe("unweighted");
    expect(submitPoolCreation).toHaveBeenCalledWith("dynamic", expect.any(Object), expect.any(String));
    wrapper.unmount();
  });

  it("edits an existing definition through the same form assembly and keeps its version guard", async () => {
    const { wrapper, state } = await setup();
    vi.mocked(getStockPool).mockResolvedValueOnce({ pool: {
      pool_id: "pool_dynamic", name: "既有动态池", pool_type: "dynamic", member_count: 0,
      metadata_version: 1, snapshot: { definition: {} },
    } } as any);
    vi.mocked(getStockPoolProducer).mockResolvedValueOnce({ producer: {
      definition_id: "definition_dynamic", pool_id: "pool_dynamic", producer_kind: "dynamic",
      schema_version: "stock-pool-producer.v1", version: 4, status: "draft", definition: ruleDefinitionRecord(baseRule),
      schedule: {}, definition_fingerprint: "definition-fingerprint",
    } });
    await state.select({ pool_id: "pool_dynamic" }, false);
    expect(state.dynamicPbMaximum).toBe(2.2);
    expect(state.dynamicTopN).toBe(25);
    expect(state.dynamicRuleBaseline).toBe(state.dynamicRuleText);
    expect((wrapper.find('[data-testid="dynamic-edit-advanced"]').element as HTMLDetailsElement).open).toBe(false);
    state.dynamicIndustry = "银行";
    state.dynamicDividendYieldMinimum = 2.5;
    await nextTick();
    expect(state.dynamicDefinitionDirty).toBe(true);

    await state.saveDynamicDefinition("draft");

    expect(updateDynamicStockPoolDefinition).toHaveBeenCalledWith("pool_dynamic", expect.objectContaining({
      status: "draft", expected_version: 4,
      rule: expect.objectContaining({
        filters: expect.arrayContaining([
          { field: "security.exchange", operator: "in", value: ["SSE", "SZSE"] },
          { field: "security.industry", operator: "eq", value: "银行" },
          { field: "daily_basic.dv_ttm", operator: "gte", value: 2.5 },
        ]),
        top_n: 25,
      }),
    }), expect.any(String));
    wrapper.unmount();
  });

  it("stops preview and creation when advanced JSON is malformed", async () => {
    const { wrapper, state } = await setup();
    state.openCreate();
    state.poolType = "dynamic";
    state.name = "有误规则";
    state.onDynamicRuleTextInput("{");
    await nextTick();

    expect(state.dynamicRuleError).not.toBe("");
    expect(wrapper.find('[data-testid="dynamic-rule-error"]').exists()).toBe(true);
    await state.submit();
    expect(previewDynamicStockPool).not.toHaveBeenCalled();
    expect(submitPoolCreation).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("normalizes Backend-supported omitted rule defaults and rejects explicit invalid values", async () => {
    const { wrapper, state } = await setup();
    state.openCreate();
    state.poolType = "dynamic";
    state.name = "简写动态规则";
    const compactRule = { base_universe: { kind: "security_master" }, top_n: 12 };
    state.onDynamicRuleTextInput(JSON.stringify(compactRule));
    expect(state.dynamicRuleError).toBe("");

    await state.previewDynamic();
    const normalizedRule: DynamicStockPoolRule = {
      schema_version: "dynamic-stock-pool-rule.v1",
      base_universe: { kind: "security_master" },
      filters: [],
      ranking: null,
      top_n: 12,
      missing_policy: "exclude",
      weight_mode: "unweighted",
      cadence: "manual",
    };
    expect(vi.mocked(previewDynamicStockPool).mock.calls[0][0]).toEqual(normalizedRule);
    await state.submit();
    expect((vi.mocked(submitPoolCreation).mock.calls[0][1] as { rule: DynamicStockPoolRule }).rule)
      .toEqual(normalizedRule);

    for (const invalidField of [
      { schema_version: null },
      { filters: null },
      { ranking: false },
      { missing_policy: null },
      { weight_mode: ["unweighted"] },
      { cadence: null },
    ]) {
      state.onDynamicRuleTextInput(JSON.stringify({ ...compactRule, ...invalidField }));
      expect(state.dynamicRuleError).not.toBe("");
    }
    state.onDynamicRuleTextInput(JSON.stringify({ ...compactRule, extra: true }));
    expect(state.dynamicRuleError).toContain("顶层字段");

    state.onDynamicRuleTextInput(JSON.stringify({
      ...compactRule,
      base_universe: { kind: "security_master", snapshot_id: "ignored-legacy-value" },
    }));
    expect(state.dynamicRuleError).toBe("");
    await state.previewDynamic();
    const normalizedCalls = vi.mocked(previewDynamicStockPool).mock.calls;
    expect(normalizedCalls[normalizedCalls.length - 1][0]).toEqual(normalizedRule);
    wrapper.unmount();
  });

  it("clears previews after rule or date edits and discards a response for an older rule", async () => {
    const { wrapper, state } = await setup();
    state.openCreate();
    state.poolType = "dynamic";

    await state.previewDynamic();
    expect(state.dynamicPreview).not.toBeNull();
    state.dynamicIndustry = "银行";
    await nextTick();
    expect(state.dynamicPreview).toBeNull();

    await state.previewDynamic();
    expect(state.dynamicPreview).not.toBeNull();
    state.onDynamicRuleTextInput(JSON.stringify({ ...baseRule, top_n: 10 }));
    expect(state.dynamicPreview).toBeNull();

    await state.previewDynamic();
    expect(state.dynamicPreview).not.toBeNull();
    state.requestedAsOf = "2026-11-13";
    expect(state.dynamicPreview).toBeNull();

    let resolvePreview: ((value: DynamicStockPoolPreview) => void) | undefined;
    vi.mocked(previewDynamicStockPool).mockImplementationOnce(() => new Promise((resolve) => {
      resolvePreview = resolve;
    }));
    const pendingPreview = state.previewDynamic();
    await nextTick();
    state.dynamicNetProfitYoyMinimum = 3;
    await nextTick();
    expect(state.dynamicPreview).toBeNull();
    resolvePreview?.({
      schema_version: "dynamic-stock-pool-preview.v1",
      authoritative: false,
      requested_as_of: "20261113",
      effective_trade_date: "20261112",
      members: [],
      member_count: 0,
      rule_fingerprint: "stale-preview",
      input_manifest: { base_universe: { row_count: 1 }, record_count: 1, selected_count: 0 },
    });
    await pendingPreview;
    expect(state.dynamicPreview).toBeNull();
    wrapper.unmount();
  });

  it("discards a pending preview across close and reopen with the same default rule and date", async () => {
    const { wrapper, state } = await setup();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    state.openCreate();
    state.poolType = "dynamic";
    const unchangedRuleText = state.dynamicRuleText;
    expect(state.requestedAsOf).toBe("");

    let resolvePreview: ((value: DynamicStockPoolPreview) => void) | undefined;
    vi.mocked(previewDynamicStockPool).mockImplementationOnce(() => new Promise((resolve) => {
      resolvePreview = resolve;
    }));
    const pendingPreview = state.previewDynamic();
    await nextTick();

    state.closeCreate();
    state.openCreate();
    expect(state.dynamicRuleText).toBe(unchangedRuleText);
    expect(state.requestedAsOf).toBe("");
    expect(state.showCreate).toBe(true);

    resolvePreview?.({
      schema_version: "dynamic-stock-pool-preview.v1",
      authoritative: false,
      requested_as_of: "",
      effective_trade_date: "20261113",
      members: [],
      member_count: 0,
      rule_fingerprint: "closed-dialog-preview",
      input_manifest: { base_universe: { row_count: 1 }, record_count: 1, selected_count: 0 },
    });
    await pendingPreview;
    expect(state.dynamicPreview).toBeNull();
    confirm.mockRestore();
    wrapper.unmount();
  });

  it("preserves opaque string and boolean conditions when an unrelated simple field changes", async () => {
    const { wrapper, state } = await setup();
    state.openCreate();
    state.poolType = "dynamic";
    const opaqueRule: DynamicStockPoolRule = {
      ...baseRule,
      filters: [
        { field: "daily_basic.pe_ttm", operator: "lte", value: "12" },
        { field: "daily_basic.pb", operator: "lte", value: true },
        { field: "security.industry", operator: "eq", value: false },
        { field: "security.exchange", operator: "eq", value: "SSE" },
      ],
    };
    state.onDynamicRuleTextInput(JSON.stringify(opaqueRule));
    expect(state.dynamicPeTtmMaximum).toBe(null);
    expect(state.dynamicPbMaximum).toBe(null);
    expect(state.dynamicIndustry).toBe("");

    state.dynamicIndustry = "银行";
    await nextTick();
    state.dynamicMinimumMarketCap = 1000;
    await nextTick();

    const edited = JSON.parse(state.dynamicRuleText) as DynamicStockPoolRule;
    expect(edited.filters).toEqual([
      { field: "daily_basic.pe_ttm", operator: "lte", value: "12" },
      { field: "daily_basic.pb", operator: "lte", value: true },
      { field: "security.industry", operator: "eq", value: false },
      { field: "security.exchange", operator: "eq", value: "SSE" },
      { field: "security.industry", operator: "eq", value: "银行" },
      { field: "daily_basic.total_mv", operator: "gte", value: 1000 },
    ]);
    expect(wrapper.find('[data-testid="dynamic-advanced-condition-notice"]').exists()).toBe(true);
    wrapper.unmount();
  });

  it("does not mark the selected dynamic pool dirty while a new pool draft is open", async () => {
    const { wrapper, state } = await setup();
    state.selected = { pool_id: "pool_dynamic", pool_type: "dynamic" };
    state.producer = { pool_id: "pool_dynamic", producer_kind: "dynamic", version: 4, definition: baseRule };
    state.loadDynamicRule(baseRule);
    state.dynamicRuleBaseline = state.dynamicRuleText;
    state.openCreate();
    state.poolType = "dynamic";
    state.dynamicIndustry = "银行";
    await nextTick();
    expect(state.dynamicDefinitionDirty).toBe(false);

    state.showCreate = false;
    state.restoreDynamicEditorAfterCreateClose();
    expect(state.dynamicIndustry).toBe("");
    expect(state.dynamicRuleText).toBe(JSON.stringify(baseRule, null, 2));
    expect(state.dynamicDefinitionDirty).toBe(false);
    wrapper.unmount();
  });
});
