import { flushPromises, shallowMount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { OperationsStatus } from "@/api/types";
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

describe("BudgetOperations", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    updateOperationsBudget.mockReset();
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
