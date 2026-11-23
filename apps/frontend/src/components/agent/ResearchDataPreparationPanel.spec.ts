import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import Panel from "./ResearchDataPreparationPanel.vue";
import { queryDataReadiness } from "@/api/dataCenter";

vi.mock("@/api/dataCenter", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/api/dataCenter")>(),
  queryDataReadiness: vi.fn(),
}));

const readiness = (verdict: "limited" | "usable") => ({
  schema_version: "data-readiness-product.v1" as const,
  verdict,
  scope: { symbol_count: 1, symbols: ["600036.SH"], start_date: "20260101", end_date: "20260331", use_case: "research" as const },
  summary: { required_sessions: 60, ready_items: verdict === "usable" ? 60 : 50, missing_items: verdict === "usable" ? 0 : 10, calendar_complete: true },
  datasets: verdict === "usable" ? [] : [{ label: "估值数据", state: "missing" as const, missing_count: 10 }],
  issues: [], issues_truncated: false, checked_against: "persisted_byq" as const,
});

const wrapperFor = () => mount(Panel, { props: {
  conversationId: "conversation-private", ownerKey: "owner-private", enabled: true, canContinue: true,
} });

describe("research data preparation panel", () => {
  afterEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("lets a user confirm an explicit scope, inspect readiness and copy a scope-only handoff", async () => {
    setActivePinia(createPinia());
    vi.mocked(queryDataReadiness).mockResolvedValueOnce(readiness("limited"));
    const clipboardWrite = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: clipboardWrite } });
    const wrapper = wrapperFor();
    await wrapper.get(".entry-button").trigger("click");
    await wrapper.get("textarea").setValue("600036.SH");
    const dates = wrapper.findAll('input[type="date"]');
    await dates[0]!.setValue("2026-01-01");
    await dates[1]!.setValue("2026-03-31");
    await wrapper.get("button.primary-button").trigger("click");
    await flushPromises();

    expect(queryDataReadiness).toHaveBeenCalledWith({
      symbols: ["600036.SH"], start_date: "20260101", end_date: "20260331", use_case: "research", data_requirements: {},
    });
    expect(wrapper.text()).toContain("所选范围部分缺失");
    expect(wrapper.text()).toContain("按交易日获取");
    expect(wrapper.text()).toContain("管理员只会看到下面列出的范围");
    const handoff = wrapper.get('input[aria-label="管理员审核链接"]');
    const url = new URL((handoff.element as HTMLInputElement).value);
    const serialized = url.searchParams.get("researchPreparation")!;
    expect(url.pathname).toBe("/settings/system/data");
    expect(url.searchParams.has("session")).toBe(false);
    expect(url.searchParams.has("conversation_id")).toBe(false);
    expect(serialized).not.toContain("conversation-private");
    expect(serialized).not.toContain("owner-private");
    expect(JSON.parse(serialized)).toEqual({
      symbols: ["600036.SH"], start_date: "20260101", end_date: "20260331", use_case: "research", data_requirements: {},
    });
    expect(sessionStorage.getItem("byq-research-preparation:owner-private:conversation-private")).not.toContain("owner-private");

    await wrapper.get(".handoff button").trigger("click");
    expect(clipboardWrite).toHaveBeenCalledWith((handoff.element as HTMLInputElement).value);
    wrapper.unmount();
  });

  it("only fills a continuation draft after a fresh usable readiness result", async () => {
    setActivePinia(createPinia());
    vi.mocked(queryDataReadiness).mockResolvedValueOnce(readiness("usable"));
    const wrapper = wrapperFor();
    await wrapper.get(".entry-button").trigger("click");
    await wrapper.get("textarea").setValue("600036.SH");
    const dates = wrapper.findAll('input[type="date"]');
    await dates[0]!.setValue("2026-01-01");
    await dates[1]!.setValue("2026-03-31");
    await wrapper.get("button.primary-button").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("所选范围覆盖检查通过");
    await wrapper.get(".next-step button").trigger("click");
    expect(wrapper.emitted("continue")?.[0]?.[0]).toContain("600036.SH");
    expect(wrapper.emitted("continue")?.[0]?.[0]).toContain("不创建股票池");
    wrapper.unmount();
  });

  it("rejects a range above the 180-day preparation limit before calling Product API", async () => {
    setActivePinia(createPinia());
    const wrapper = wrapperFor();
    await wrapper.get(".entry-button").trigger("click");
    await wrapper.get("textarea").setValue("600036.SH");
    const dates = wrapper.findAll('input[type="date"]');
    await dates[0]!.setValue("2026-01-01");
    await dates[1]!.setValue("2026-07-01");
    await wrapper.get("button.primary-button").trigger("click");
    expect(wrapper.text()).toContain("最多覆盖 180 个自然日");
    expect(queryDataReadiness).not.toHaveBeenCalled();
    wrapper.unmount();
  });
});
