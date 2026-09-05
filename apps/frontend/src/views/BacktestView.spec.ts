import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ElementPlus from "element-plus";
import BacktestView from "./BacktestView.vue";
import { useAuthStore } from "@/stores/auth";

const replaceRoute = vi.fn();
const pushRoute = vi.fn();
vi.mock("vue-router", () => ({
  useRoute: () => ({ path: "/backtest", query: {} }),
  useRouter: () => ({ replace: replaceRoute, push: pushRoute }),
}));

const listBacktests = vi.fn();
const getBacktest = vi.fn();
const listBacktestOptions = vi.fn();
const listSignalSnapshots = vi.fn();
const submitBacktest = vi.fn();
vi.mock("@/api/quant", () => ({
  cancelBacktest: vi.fn(),
  createSignalProducerJob: vi.fn(),
  deleteBacktest: vi.fn(),
  getBacktestAnalysis: vi.fn(),
  getBacktest: (...args: unknown[]) => getBacktest(...args),
  getBacktestManifest: vi.fn(),
  getSignalProducerJob: vi.fn(),
  listBacktests: (...args: unknown[]) => listBacktests(...args),
  listBacktestOptions: (...args: unknown[]) => listBacktestOptions(...args),
  listSignalSnapshots: (...args: unknown[]) => listSignalSnapshots(...args),
  runBacktest: vi.fn(),
  submitBacktest: (...args: unknown[]) => submitBacktest(...args),
}));

const listStockPools = vi.fn();
vi.mock("@/api/paper", () => ({
  listStockPools: (...args: unknown[]) => listStockPools(...args),
}));

function mountView() {
  return mount(BacktestView, {
    global: {
      plugins: [ElementPlus],
      stubs: {
        ChartWrapper: true,
        MetricCard: true,
      },
    },
  });
}

describe("BacktestView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    useAuthStore().token = "backtest-test";
    replaceRoute.mockReset();
    pushRoute.mockReset();
    listBacktests.mockReset();
    getBacktest.mockReset();
    listBacktestOptions.mockReset();
    listSignalSnapshots.mockReset();
    listStockPools.mockReset();
    submitBacktest.mockReset();
    const row = {
      job_id: "backtest_1234567890abcdef1234567890abcdef",
      name: "沪深300动量验证",
      status: "queued",
      summary: {},
      created_at: "2026-09-05T04:00:00Z",
    };
    listBacktests.mockResolvedValue({ backtests: [row], total: 1, limit: 20, offset: 0 });
    getBacktest.mockResolvedValue(row);
    listBacktestOptions.mockResolvedValue({ options: [] });
    listSignalSnapshots.mockResolvedValue({ snapshots: [] });
    listStockPools.mockResolvedValue({ pools: [] });
    submitBacktest.mockResolvedValue({ job: row });
  });

  it("shows a readable name separately from the technical backtest ID", async () => {
    const wrapper = mountView();
    await flushPromises();

    expect(wrapper.text()).toContain("沪深300动量验证");
    expect(wrapper.text()).toContain("回测 ID");
    expect(wrapper.text()).toContain("backtest…cdef");
    expect((wrapper.vm as unknown as { job: { job_id: string } }).job.job_id)
      .toBe("backtest_1234567890abcdef1234567890abcdef");
  });

  it("submits the optional readable name without changing frozen inputs", async () => {
    const wrapper = mountView();
    await flushPromises();
    const state = wrapper.vm as unknown as {
      backtestName: string;
      selectedOption: Record<string, unknown> | null;
      selectedSnapshot: Record<string, unknown> | null;
      submitCreate: () => Promise<void>;
    };
    state.backtestName = "价值策略季度复核";
    state.selectedOption = {
      task_id: "task_1",
      strategy_version_artifact_id: "artifact_strategy",
      approval_artifact_id: "artifact_approval",
    };
    state.selectedSnapshot = { artifact_id: "artifact_snapshot" };

    await state.submitCreate();

    expect(submitBacktest).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "价值策略季度复核",
        signal_snapshot_artifact_id: "artifact_snapshot",
      }),
      "backtest-test",
    );
  });
});
