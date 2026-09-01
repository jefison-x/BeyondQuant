import { flushPromises, shallowMount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MLResearchWorkbench from "./MLResearchWorkbench.vue";

const getMLWorkspace = vi.fn();
const getMLPredictionRows = vi.fn();

vi.mock("vue-router", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/api/mlResearch", () => ({
  approveMLStrategy: vi.fn(),
  createMLPrediction: vi.fn(),
  createMLStrategy: vi.fn(),
  createMLTraining: vi.fn(),
  getMLPrediction: vi.fn(),
  getMLPredictionRows: (...args: unknown[]) => getMLPredictionRows(...args),
  getMLTraining: vi.fn(),
  getMLWorkspace: (...args: unknown[]) => getMLWorkspace(...args),
}));
vi.mock("@/api/research", () => ({ createTask: vi.fn() }));
vi.mock("@/api/quant", () => ({
  getBacktest: vi.fn(), runBacktest: vi.fn(), submitBacktest: vi.fn(),
}));

describe("MLResearchWorkbench", () => {
  beforeEach(() => {
    getMLPredictionRows.mockReset();
    getMLPredictionRows.mockResolvedValue({ rows: [], total: 0, limit: 50, offset: 0 });
    getMLWorkspace.mockReset();
    getMLWorkspace.mockResolvedValue({
      tasks: [{ task_id: "task_1", title: "模型研究" }],
      pools: [],
      artifacts: [{
        artifact_id: "artifact_strategy", task_id: "task_1", kind: "ml_strategy_version",
        status: "validated", created_at: "2026-09-02T00:00:00Z", content: { name: "测试模型" },
      }],
      training_runs: [{
        training_run_id: "mlrun_1", ml_strategy_artifact_id: "artifact_strategy",
        status: "completed", model_artifact_id: "artifact_model",
      }],
      prediction_runs: [{
        prediction_run_id: "mlpred_1", ml_strategy_artifact_id: "artifact_strategy",
        status: "completed", signal_artifact_id: "artifact_signal",
      }],
      backtests: [],
    });
  });

  it("loads paged prediction rows only after the prediction tab is opened", async () => {
    const wrapper = shallowMount(MLResearchWorkbench);
    await flushPromises();

    expect(getMLPredictionRows).not.toHaveBeenCalled();

    (wrapper.vm as unknown as { activeTab: string }).activeTab = "prediction";
    await flushPromises();

    expect(getMLPredictionRows).toHaveBeenCalledWith("mlpred_1", "", 50, 0);
  });
});
