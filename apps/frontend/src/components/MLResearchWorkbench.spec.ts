import { flushPromises, shallowMount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MLResearchWorkbench from "./MLResearchWorkbench.vue";

const getMLCapabilities = vi.fn();
const getMLOptions = vi.fn();
const getMLStudies = vi.fn();
const getMLStudy = vi.fn();
const getMLPredictionRows = vi.fn();
const createMLTraining = vi.fn();
const deleteMLStudy = vi.fn();
const confirmTraining = vi.fn();

vi.mock("element-plus", () => ({
  ElMessage: { success: vi.fn(), error: vi.fn() },
  ElMessageBox: { confirm: (...args: unknown[]) => confirmTraining(...args) },
}));

vi.mock("vue-router", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/api/mlResearch", () => ({
  approveMLStrategy: vi.fn(),
  createMLPrediction: vi.fn(),
  createMLStrategy: vi.fn(),
  createMLTraining: (...args: unknown[]) => createMLTraining(...args),
  deleteMLStudy: (...args: unknown[]) => deleteMLStudy(...args),
  getMLPrediction: vi.fn(),
  getMLPredictionRows: (...args: unknown[]) => getMLPredictionRows(...args),
  getMLTraining: vi.fn(),
  getMLCapabilities: (...args: unknown[]) => getMLCapabilities(...args),
  getMLOptions: (...args: unknown[]) => getMLOptions(...args),
  getMLStudies: (...args: unknown[]) => getMLStudies(...args),
  getMLStudy: (...args: unknown[]) => getMLStudy(...args),
}));
vi.mock("@/api/research", () => ({ createTask: vi.fn() }));
vi.mock("@/api/quant", () => ({
  getBacktest: vi.fn(), runBacktest: vi.fn(), submitBacktest: vi.fn(),
}));

describe("MLResearchWorkbench", () => {
  beforeEach(() => {
    getMLPredictionRows.mockReset();
    getMLPredictionRows.mockResolvedValue({ rows: [], total: 0, limit: 50, offset: 0 });
    getMLCapabilities.mockReset();
    getMLCapabilities.mockResolvedValue({
      schema_version: "ml-capabilities.v1", capabilities: [{
        capability_id: "lightgbm-return-ranking", name: "LightGBM 收益排序",
        learner: { kind: "lightgbm_regression", profile: "byq-lightgbm-cpu-v1" },
        feature_set: { id: "price-volume-basic-v1" },
      }], limitations: [], registry: { schema_version: "ml-capability-registry.v2", content_sha256: "hash", components: [
        { id: "price-volume-basic-v1", kind: "feature_set", display_name: "基础价量", status: "qualified", parameters: {}, limits: {}, content_sha256: "a" },
        { id: "forward-return-v1", kind: "target", display_name: "未来收益", status: "qualified", parameters: {}, limits: {}, content_sha256: "b" },
        { id: "walk-forward-purged-v1", kind: "validation_plan", display_name: "净化走步", status: "qualified", parameters: {}, limits: {}, content_sha256: "c" },
        { id: "byq-lightgbm-cpu-v1", kind: "learner_profile", display_name: "LightGBM", status: "qualified", parameters: {}, limits: {}, content_sha256: "d" },
        { id: "top-n-equal-weight-v1", kind: "portfolio_policy", display_name: "Top-N", status: "qualified", parameters: {}, limits: {}, content_sha256: "e" },
      ] },
    });
    getMLOptions.mockReset();
    getMLOptions.mockResolvedValue({ schema_version: "ml-options.v1", tasks: [{ task_id: "task_1", title: "模型研究" }], pools: [] });
    getMLStudies.mockReset();
    getMLStudies.mockResolvedValue({ schema_version: "ml-study-catalog.v1", total: 1, limit: 12, offset: 0, has_more: false, studies: [{
      artifact_id: "artifact_strategy", task_id: "task_1", task_title: "模型研究", name: "测试模型",
      schema_version: "ml-strategy-version.v1", status: "validated", regime_enabled: false, stage: "signal",
    }] });
    getMLStudy.mockReset();
    createMLTraining.mockReset();
    createMLTraining.mockResolvedValue({ training_run: {
      training_run_id: "mlrun_new", ml_strategy_artifact_id: "artifact_strategy",
      stock_pool_snapshot_id: "snapshot_1", status: "waiting_for_data",
    } });
    deleteMLStudy.mockReset();
    deleteMLStudy.mockResolvedValue({
      schema_version: "ml-study-delete.v1",
      study: { artifact_id: "artifact_strategy", status: "superseded" },
      invalidated_approval_ids: ["artifact_approval"],
    });
    confirmTraining.mockReset();
    confirmTraining.mockResolvedValue("confirm");
    getMLStudy.mockResolvedValue({
      schema_version: "ml-product-study-detail.v1",
      study: {
        artifact_id: "artifact_strategy", task_id: "task_1", kind: "ml_strategy_version",
        status: "validated", created_at: "2026-09-02T00:00:00Z", content: { name: "测试模型", schema_version: "ml-strategy-version.v1" },
      },
      approval_artifact_id: "artifact_approval",
      tasks: [{ task_id: "task_1", title: "模型研究" }],
      artifacts: [{
        artifact_id: "artifact_signal", task_id: "task_1", kind: "signal_snapshot",
        status: "validated", content: {},
      }], training_runs: { total: 1, runs: [{
        training_run_id: "mlrun_1", ml_strategy_artifact_id: "artifact_strategy",
        status: "completed", model_artifact_id: "artifact_model",
      }] }, prediction_runs: { total: 1, runs: [{
        prediction_run_id: "mlpred_1", ml_strategy_artifact_id: "artifact_strategy",
        status: "completed", signal_artifact_id: "artifact_signal",
      }] }, backtests: { total: 0, backtests: [] },
    });
  });

  it("loads detail and paged prediction rows only after explicit selection", async () => {
    const wrapper = shallowMount(MLResearchWorkbench);
    await flushPromises();

    expect(getMLStudy).not.toHaveBeenCalled();
    expect(getMLPredictionRows).not.toHaveBeenCalled();

    await (wrapper.vm as unknown as { selectStudy: (id: string) => Promise<void> }).selectStudy("artifact_strategy");
    await flushPromises();
    expect(getMLStudy).toHaveBeenCalledWith("artifact_strategy");
    expect(getMLPredictionRows).not.toHaveBeenCalled();

    (wrapper.vm as unknown as { activeTab: string }).activeTab = "prediction";
    await flushPromises();

    expect(getMLPredictionRows).toHaveBeenCalledWith("mlpred_1", "", 50, 0);
  });

  it("latches before confirmation so rapid clicks create only one training run", async () => {
    getMLOptions.mockResolvedValueOnce({
      schema_version: "ml-options.v1", tasks: [{ task_id: "task_1", title: "模型研究" }],
      pools: [{
        pool_id: "pool_1", name: "沪深300", status: "active", member_count: 300,
        current_snapshot_id: "snapshot_1",
      }],
    });
    let resolveConfirmation: (value: string) => void = () => undefined;
    confirmTraining.mockReturnValueOnce(new Promise(resolve => { resolveConfirmation = resolve; }));
    const wrapper = shallowMount(MLResearchWorkbench);
    await flushPromises();
    const vm = wrapper.vm as any;
    await vm.selectStudy("artifact_strategy");
    vm.training = null;
    vm.form.pool_id = "pool_1";

    const first = vm.approveAndTrain();
    const second = vm.approveAndTrain();
    expect(confirmTraining).toHaveBeenCalledTimes(1);
    resolveConfirmation("confirm");
    await Promise.all([first, second]);

    expect(createMLTraining).toHaveBeenCalledTimes(1);
    expect(createMLTraining.mock.calls[0][1]).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("deletes a never-executed study after confirmation and refreshes the catalog", async () => {
    getMLStudy.mockResolvedValueOnce({
      schema_version: "ml-product-study-detail.v1",
      study: {
        artifact_id: "artifact_strategy", task_id: "task_1", kind: "ml_strategy_version",
        status: "validated", content: { name: "待删除研究", schema_version: "ml-strategy-version.v2" },
      },
      approval_artifact_id: "artifact_approval",
      artifacts: [],
      training_runs: { total: 0, runs: [] },
      prediction_runs: { total: 0, runs: [] },
      backtests: { total: 0, backtests: [] },
    });
    const wrapper = shallowMount(MLResearchWorkbench);
    await flushPromises();
    const vm = wrapper.vm as any;
    await vm.selectStudy("artifact_strategy");
    expect(vm.canDeleteStudy).toBe(true);

    await vm.removeStudy();

    expect(deleteMLStudy).toHaveBeenCalledWith("artifact_strategy");
    expect(vm.selectedStrategy).toBe("");
    expect(vm.detail).toBeNull();
    expect(getMLStudies).toHaveBeenCalledTimes(2);
  });
});
