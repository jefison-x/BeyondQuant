import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import Panel from "./ResearchDataPreparationPanel.vue";
import {
  createConversationResearchPreparation,
  getConversationResearchPreparation,
  listConversationResearchPreparations,
  queryDataReadiness,
  retryConversationResearchPreparation,
  stopConversationResearchContinuation,
} from "@/api/dataCenter";
import type { ConversationResearchPreparationReceipt } from "@/api/dataCenter";

vi.mock("@/api/dataCenter", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/api/dataCenter")>(),
  createConversationResearchPreparation: vi.fn(),
  getConversationResearchPreparation: vi.fn(),
  listConversationResearchPreparations: vi.fn(),
  queryDataReadiness: vi.fn(),
  retryConversationResearchPreparation: vi.fn(),
  stopConversationResearchContinuation: vi.fn(),
}));

const scope = {
  symbols: ["600036.SH"], start_date: "20260101", end_date: "20260331", use_case: "research" as const,
  data_requirements: {},
};

const readiness = (verdict: "limited" | "usable", checkedScope = scope) => ({
  schema_version: "data-readiness-product.v1" as const,
  verdict,
  scope: {
    symbol_count: checkedScope.symbols.length,
    symbols: [...checkedScope.symbols],
    start_date: checkedScope.start_date,
    end_date: checkedScope.end_date,
    use_case: "research" as const,
  },
  summary: { required_sessions: 60, ready_items: verdict === "usable" ? 60 : 50, missing_items: verdict === "usable" ? 0 : 10, calendar_complete: true },
  datasets: verdict === "usable" ? [] : [{ label: "估值数据", state: "missing" as const, missing_count: 10 }],
  issues: [], issues_truncated: false, checked_against: "persisted_byq" as const,
});

const receipt = (
  status: string,
  requestId: string | null = "datademand_1",
  receiptScope = scope,
  autoStatus?: NonNullable<ConversationResearchPreparationReceipt["auto_continuation"]>["status"],
): ConversationResearchPreparationReceipt => ({
  request_id: requestId, status, scope: receiptScope,
  ...(autoStatus ? { auto_continuation: { status: autoStatus } } : {}),
});

const setPageVisibility = (visibilityState: DocumentVisibilityState) => {
  Object.defineProperty(document, "visibilityState", { configurable: true, value: visibilityState });
};

const wrapperFor = (enabled = true) => mount(Panel, { props: {
  conversationId: "conversation-private", ownerKey: "owner-private", enabled, canContinue: true,
} });

describe("research data preparation panel", () => {
  beforeEach(() => {
    vi.mocked(queryDataReadiness).mockReset();
    vi.mocked(createConversationResearchPreparation).mockReset();
    vi.mocked(getConversationResearchPreparation).mockReset();
    vi.mocked(retryConversationResearchPreparation).mockReset();
    vi.mocked(stopConversationResearchContinuation).mockReset();
    vi.mocked(listConversationResearchPreparations).mockReset().mockResolvedValue({ preparations: [] });
    setPageVisibility("visible");
  });

  afterEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    vi.useRealTimers();
  });

  it("shows and monitors automatic preparation, and stops only the pending exact continuation", async () => {
    vi.useFakeTimers();
    vi.mocked(listConversationResearchPreparations).mockResolvedValueOnce({
      preparations: [receipt("running", "datademand_auto", scope, "waiting")],
    });
    vi.mocked(getConversationResearchPreparation).mockResolvedValueOnce(
      receipt("completed", "datademand_auto", scope, "dispatching"),
    );
    vi.mocked(stopConversationResearchContinuation).mockResolvedValueOnce(
      receipt("completed", "datademand_auto", scope, "cancelled"),
    );
    const wrapper = wrapperFor(false);
    await flushPromises();

    expect(wrapper.text()).toContain("后台正在准备数据；完成后将自动复查并继续原研究。");
    expect(wrapper.text()).not.toContain("仍需重新检查同一范围的数据覆盖");
    expect(wrapper.findAll("button").some((button) => button.text() === "停止自动续研")).toBe(true);
    expect(queryDataReadiness).not.toHaveBeenCalled();
    expect(createConversationResearchPreparation).not.toHaveBeenCalled();
    expect(wrapper.emitted("continue")).toBeUndefined();

    await vi.advanceTimersByTimeAsync(30_000);
    await flushPromises();
    expect(getConversationResearchPreparation).toHaveBeenCalledWith("conversation-private", "datademand_auto");
    expect(wrapper.text()).toContain("正在原会话自动继续研究");

    await wrapper.findAll("button").find((button) => button.text() === "停止自动续研")!.trigger("click");
    await flushPromises();
    expect(stopConversationResearchContinuation).toHaveBeenCalledWith("conversation-private", "datademand_auto");
    expect(wrapper.text()).toContain("自动续研已停止");
    expect(wrapper.findAll("button").some((button) => button.text().includes("准备研究数据"))).toBe(true);
    expect(queryDataReadiness).not.toHaveBeenCalled();
    expect(createConversationResearchPreparation).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("pauses receipt polling while hidden and leaves bound root cancellation to the chat Stop action", async () => {
    vi.useFakeTimers();
    setPageVisibility("hidden");
    vi.mocked(listConversationResearchPreparations).mockResolvedValueOnce({
      preparations: [receipt("completed", "datademand_bound", scope, "bound")],
    });
    vi.mocked(getConversationResearchPreparation).mockResolvedValueOnce(
      receipt("completed", "datademand_bound", scope, "succeeded"),
    );
    const wrapper = wrapperFor();
    await flushPromises();

    expect(wrapper.text()).toContain("请使用会话下方的“停止本轮”");
    expect(wrapper.findAll("button").some((button) => button.text().includes("停止自动续研"))).toBe(false);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(getConversationResearchPreparation).not.toHaveBeenCalled();

    setPageVisibility("visible");
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(0);
    await flushPromises();
    expect(getConversationResearchPreparation).toHaveBeenCalledWith("conversation-private", "datademand_bound");
    expect(wrapper.text()).toContain("已完成自动续研");
    expect(stopConversationResearchContinuation).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("submits only the freshly checked scope after the user explicitly asks for preparation", async () => {
    vi.mocked(queryDataReadiness).mockResolvedValueOnce(readiness("limited"));
    vi.mocked(createConversationResearchPreparation).mockResolvedValueOnce(receipt("queued"));
    const wrapper = wrapperFor();
    await flushPromises();
    await wrapper.get(".entry-button").trigger("click");
    await wrapper.get("textarea").setValue("600036.SH");
    const dates = wrapper.findAll('input[type="date"]');
    await dates[0]!.setValue("2026-01-01");
    await dates[1]!.setValue("2026-03-31");
    await wrapper.findAll("button.primary-button")[0]!.trigger("click");
    await flushPromises();

    expect(queryDataReadiness).toHaveBeenCalledWith(scope);
    expect(createConversationResearchPreparation).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("所选范围部分缺失");
    expect(wrapper.text()).toContain("手动准备入口");
    expect(wrapper.text()).not.toContain("管理员审核链接");

    await wrapper.findAll("button.primary-button").find((button) => button.text().includes("为当前会话准备缺失数据"))!.trigger("click");
    await flushPromises();
    expect(createConversationResearchPreparation).toHaveBeenCalledWith("conversation-private", scope);
    expect(wrapper.text()).toContain("补数请求已排队");
    expect(wrapper.text()).toContain("datademand_1");
    expect(wrapper.emitted("continue")).toBeUndefined();
    wrapper.unmount();
  });

  it("accepts a sorted backend receipt for an unsorted user symbol selection without reordering submission", async () => {
    const userScope = { ...scope, symbols: ["601398.SH", "600036.SH"] };
    const sortedBackendScope = { ...userScope, symbols: ["600036.SH", "601398.SH"] };
    expect(sortedBackendScope.symbols).not.toEqual(userScope.symbols);
    vi.mocked(queryDataReadiness).mockResolvedValueOnce(readiness("limited", userScope));
    vi.mocked(createConversationResearchPreparation).mockResolvedValueOnce(receipt("queued", "datademand_2", sortedBackendScope));
    const wrapper = wrapperFor();
    await flushPromises();
    await wrapper.get(".entry-button").trigger("click");
    await wrapper.get("textarea").setValue("601398.SH, 600036.SH");
    const dates = wrapper.findAll('input[type="date"]');
    await dates[0]!.setValue("2026-01-01");
    await dates[1]!.setValue("2026-03-31");
    await wrapper.findAll("button.primary-button")[0]!.trigger("click");
    await flushPromises();

    expect(queryDataReadiness).toHaveBeenCalledWith(userScope);
    expect(createConversationResearchPreparation).not.toHaveBeenCalled();
    await wrapper.findAll("button.primary-button").find((button) => button.text().includes("为当前会话准备缺失数据"))!.trigger("click");
    await flushPromises();

    expect(createConversationResearchPreparation).toHaveBeenCalledWith("conversation-private", userScope);
    expect(wrapper.text()).toContain("补数请求已排队");
    expect(wrapper.text()).not.toContain("回执与刚才检查的范围不一致");
    wrapper.unmount();
  });

  it("hydrates a prior receipt but requires a fresh coverage readback before offering a draft", async () => {
    vi.mocked(listConversationResearchPreparations).mockResolvedValueOnce({ preparations: [receipt("completed")] });
    vi.mocked(getConversationResearchPreparation).mockResolvedValueOnce(receipt("completed"));
    vi.mocked(queryDataReadiness).mockResolvedValueOnce(readiness("usable"));
    const wrapper = wrapperFor();
    await flushPromises();
    expect(listConversationResearchPreparations).toHaveBeenCalledWith("conversation-private");
    await wrapper.get(".entry-button").trigger("click");
    expect(wrapper.get("textarea").element).toHaveProperty("value", "600036.SH");
    expect(wrapper.text()).toContain("补数任务已结束，请复查数据覆盖");
    expect(wrapper.text()).not.toContain("带入续研草稿");
    expect(queryDataReadiness).not.toHaveBeenCalled();

    await wrapper.findAll("button").find((button) => button.text() === "只读刷新准备状态")!.trigger("click");
    await flushPromises();
    expect(getConversationResearchPreparation).toHaveBeenCalledWith("conversation-private", "datademand_1");

    await wrapper.findAll("button").find((button) => button.text() === "确认范围并检查数据")!.trigger("click");
    await flushPromises();
    expect(queryDataReadiness).toHaveBeenCalledWith(scope);
    expect(wrapper.text()).toContain("带入续研草稿");
    expect(wrapper.emitted("continue")).toBeUndefined();
    await wrapper.findAll("button").find((button) => button.text() === "带入续研草稿")!.trigger("click");
    expect(wrapper.emitted("continue")?.[0]?.[0]).toContain("600036.SH");
    expect(wrapper.emitted("continue")?.[0]?.[0]).toContain("不创建股票池");
    wrapper.unmount();
  });

  it("requires renewed explicit confirmation before retrying a failed exact-scope request", async () => {
    const failed = { ...receipt("failed"), retry_token: "retry-once", error: "供应商暂不可用" };
    vi.mocked(listConversationResearchPreparations).mockResolvedValueOnce({ preparations: [failed] });
    vi.mocked(queryDataReadiness).mockResolvedValueOnce(readiness("limited"));
    vi.mocked(retryConversationResearchPreparation).mockResolvedValueOnce(receipt("queued"));
    const wrapper = wrapperFor();
    await flushPromises();
    await wrapper.get(".entry-button").trigger("click");
    await wrapper.get("button.primary-button").trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("补数失败");
    expect(wrapper.text()).toContain("供应商暂不可用");
    const retryButton = wrapper.findAll("button").find((button) => button.text().includes("确认重试此补数请求"))!;
    expect((retryButton.element as HTMLButtonElement).disabled).toBe(true);
    await wrapper.get('.retry-box input[type="checkbox"]').setValue(true);
    await retryButton.trigger("click");
    await flushPromises();
    expect(retryConversationResearchPreparation).toHaveBeenCalledWith("conversation-private", "datademand_1", "retry-once");
    expect(wrapper.text()).toContain("补数请求已排队");
    wrapper.unmount();
  });

  it("shows an unpublished-data receipt without treating it as a queued job", async () => {
    vi.mocked(listConversationResearchPreparations).mockResolvedValueOnce({ preparations: [
      { ...receipt("not_published", null), error: "当日收盘行情尚未发布" },
    ] });
    vi.mocked(queryDataReadiness).mockResolvedValueOnce(readiness("limited"));
    const wrapper = wrapperFor();
    await flushPromises();
    await wrapper.get(".entry-button").trigger("click");
    expect(wrapper.text()).toContain("所需行情尚未发布，暂未创建补数任务");
    expect(wrapper.text()).toContain("日历就绪不代表收盘行情已发布");
    expect(wrapper.text()).not.toContain("请求编号");
    expect(createConversationResearchPreparation).not.toHaveBeenCalled();

    await wrapper.findAll("button.primary-button")[0]!.trigger("click");
    await flushPromises();
    expect(wrapper.findAll("button.primary-button").some((button) => button.text().includes("稍后重新检查行情是否已发布"))).toBe(true);
    expect(createConversationResearchPreparation).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("rejects a range above the 180-day preparation limit before calling Product API", async () => {
    const wrapper = wrapperFor();
    await flushPromises();
    await wrapper.get(".entry-button").trigger("click");
    await wrapper.get("textarea").setValue("600036.SH");
    const dates = wrapper.findAll('input[type="date"]');
    await dates[0]!.setValue("2026-01-01");
    await dates[1]!.setValue("2026-07-01");
    await wrapper.get("button.primary-button").trigger("click");
    expect(wrapper.text()).toContain("最多覆盖 180 个自然日");
    expect(queryDataReadiness).not.toHaveBeenCalled();
    expect(createConversationResearchPreparation).not.toHaveBeenCalled();
    wrapper.unmount();
  });
});
