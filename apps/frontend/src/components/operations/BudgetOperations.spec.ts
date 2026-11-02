import { flushPromises, shallowMount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { OperationsReceiptUsage, OperationsStatus } from "@/api/types";
import BudgetOperations from "./BudgetOperations.vue";

const updateOperationsBudget = vi.fn();
vi.mock("@/api/operations", () => ({
  updateOperationsBudget: (...args: unknown[]) => updateOperationsBudget(...args),
}));

const data = {
  budget: {
    policy_id: "product-agent",
    enabled: true,
    alert_total_tokens: 400000,
    alert_requests: 48,
    version: 3,
    updated_by: "admin",
    updated_at: "2026-08-28T00:00:00Z",
  },
  runtime: {
    usage: {
      total_tokens: 10,
      model_calls: 1,
      reasoning_tokens: 2,
    },
  },
} as OperationsStatus;

const receiptUsage: OperationsReceiptUsage = {
  schema_version: "operations-usage.v1",
  scope: "persisted_continuation_requests",
  source: "backend_validated_request_receipts",
  completeness: "partial",
  request_count: 1,
  known_requests: 1,
  unknown_requests: 0,
  invalid_requests: 0,
  known_totals: {
    input_tokens: 47589,
    cache_read_tokens: 319232,
    output_tokens: 1539,
    provider_attempts: 8,
    total_tokens: 368360,
  },
  uncovered_sources: ["ordinary_product_roots", "research_judgment"],
  truncated: false,
};

describe("BudgetOperations", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    updateOperationsBudget.mockReset();
  });

  it("shows persistent receipt totals instead of Runtime process counters", () => {
    const wrapper = shallowMount(BudgetOperations, { props: { data: { ...data, usage: receiptUsage } } });
    expect(wrapper.findAll(".ops-metrics strong").map((node) => node.text())).toEqual(["368,360", "8", "1"]);
    expect(wrapper.find(".usage-breakdown").text()).toContain("非缓存输入 47,589 · 缓存读取 319,232 · 输出 1,539");
    expect(wrapper.find("el-alert").attributes("title")).toContain("普通回合和研究判断尚未计入");
  });

  it("does not fall back to process counters when the summary is unavailable", () => {
    const wrapper = shallowMount(BudgetOperations, { props: { data } });
    expect(wrapper.findAll(".ops-metrics strong").map((node) => node.text())).toEqual(["暂无已知回执", "暂无已知回执", "未知"]);
    expect(wrapper.text()).toContain("用量汇总暂不可用");
  });

  it("keeps unknown requests separate from a proven zero receipt", async () => {
    const zero = { input_tokens: 0, cache_read_tokens: 0, output_tokens: 0, provider_attempts: 0, total_tokens: 0 };
    const usage = { ...receiptUsage, known_requests: 0, unknown_requests: 1, known_totals: zero };
    const wrapper = shallowMount(BudgetOperations, { props: { data: { ...data, usage } } });
    expect(wrapper.findAll(".ops-metrics strong")[0].text()).toBe("暂无已知回执");
    expect(wrapper.text()).toContain("未确认 1");
    await wrapper.setProps({ data: { ...data, usage: { ...usage, known_requests: 1, unknown_requests: 0 } } });
    expect(wrapper.findAll(".ops-metrics strong").map((node) => node.text())).toEqual(["0", "0", "1"]);
  });

  it("labels an incomplete record window", () => {
    const wrapper = shallowMount(BudgetOperations, { props: { data: { ...data, usage: { ...receiptUsage, truncated: true } } } });
    expect(wrapper.text()).toContain("当前只汇总了部分记录");
  });

  it("saves in browsers without crypto.randomUUID", async () => {
    vi.stubGlobal("crypto", {
      getRandomValues: (bytes: Uint8Array) => {
        bytes.fill(0x12);
        return bytes;
      },
    });
    updateOperationsBudget.mockResolvedValue({ version: 4 });
    const wrapper = shallowMount(BudgetOperations, { props: { data } });

    await wrapper.find("el-button").trigger("click");
    await flushPromises();

    expect(updateOperationsBudget).toHaveBeenCalledWith(expect.objectContaining({
      expected_version: 3,
      idempotency_key: "budget-3-12121212-1212-4212-9212-121212121212",
    }));
    expect(wrapper.text()).toContain("监控阈值已更新并写入追加审计");
  });
});
