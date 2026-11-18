import { flushPromises, shallowMount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import MLResearchWorkbench from "./MLResearchWorkbench.vue";
import { useAuthStore } from "@/stores/auth";
import { createMLStrategy } from "@/api/mlResearch";
import { createTask } from "@/api/research";

const getMLCapabilities = vi.fn();
const getMLOptions = vi.fn();
const getMLStudies = vi.fn();
const getMLStudy = vi.fn();
const getMLPredictionRows = vi.fn();
const createMLTraining = vi.fn();
const getMLTrainingSubmission = vi.fn();
const deleteMLStudy = vi.fn();
const setMLStudyLifecycle = vi.fn();
const confirmTraining = vi.fn();
const submitProductApprovalRequestOnce = vi.fn();

vi.mock("element-plus", () => ({
  ElMessage: { success: vi.fn(), error: vi.fn() },
  ElMessageBox: { confirm: (...args: unknown[]) => confirmTraining(...args) },
}));

vi.mock("vue-router", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/api/mlResearch", () => ({
  createMLPrediction: vi.fn(),
  createMLStrategy: vi.fn(),
  createMLTraining: (...args: unknown[]) => createMLTraining(...args),
  deleteMLStudy: (...args: unknown[]) => deleteMLStudy(...args),
  setMLStudyLifecycle: (...args: unknown[]) => setMLStudyLifecycle(...args),
  getMLPrediction: vi.fn(),
  getMLPredictionRows: (...args: unknown[]) => getMLPredictionRows(...args),
  getMLTraining: vi.fn(),
  getMLTrainingSubmission: (...args: unknown[]) => getMLTrainingSubmission(...args),
  getMLCapabilities: (...args: unknown[]) => getMLCapabilities(...args),
  getMLOptions: (...args: unknown[]) => getMLOptions(...args),
  getMLStudies: (...args: unknown[]) => getMLStudies(...args),
  getMLStudy: (...args: unknown[]) => getMLStudy(...args),
}));
vi.mock("@/api/research", () => ({ createTask: vi.fn() }));
vi.mock("@/api/approvalRequestSubmissions", () => ({
  submitProductApprovalRequestOnce: (...args: unknown[]) => submitProductApprovalRequestOnce(...args),
}));
vi.mock("@/api/quant", () => ({
  getBacktest: vi.fn(), runBacktest: vi.fn(), submitBacktest: vi.fn(),
}));

function optionsWithDateRecommendation(poolId: string, snapshotId: string, horizon: number, year: string) {
  const dates = {
    train_start: `${year}0102`, train_end: `${year}0216`,
    validation_start: `${year}0219`, validation_end: `${year}0228`,
    prediction_start: `${year}0303`, prediction_end: `${year}0314`,
  };
  return {
    schema_version: "ml-options.v1", tasks: [], pools: [{
      pool_id: poolId, name: poolId, status: "active", member_count: 5, current_snapshot_id: snapshotId,
    }],
    selected_pool_data_reference: {
      pool_id: poolId, stock_pool_snapshot_id: snapshotId, state: "observed_bounds",
      member_count: 5, members_with_data: 5, minimum_rows_per_member: 60,
      observed_start_date: dates.train_start, observed_end_date: dates.prediction_end,
      reference_only: true as const, continuous_history_verified: false as const,
      training_readiness_verified: false as const,
      recommendation: {
        state: "available" as const, reason: null, mode: "compatible" as const,
        horizon_sessions: horizon, counts: { train: 60, validation: 10, prediction: 5 },
        window_start: dates.train_start, window_end: dates.prediction_end,
        continuous_history_verified: true, minimum_samples_verified: true,
        training_quality_verified: false as const,
      },
      recommended_dates: dates,
    },
  };
}

describe("MLResearchWorkbench", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.mocked(createMLStrategy).mockReset();
    vi.mocked(createTask).mockReset();
    useAuthStore().setUser({ subject: "alice", workspace: { workspace_id: "workspace-alice" } } as any);
    submitProductApprovalRequestOnce.mockReset();
    localStorage.clear(); sessionStorage.clear();
    getMLTrainingSubmission.mockReset();
    getMLTrainingSubmission.mockResolvedValue({ receipt_watch: {
      watch_id: "mlwatch_test", state: "awaiting_receipt", check_count: 1, check_limit: 8,
    } });
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
    setMLStudyLifecycle.mockReset();
    setMLStudyLifecycle.mockResolvedValue({
      schema_version: "ml-study-lifecycle.v1",
      study: { artifact_id: "artifact_strategy", status: "archived" },
      management: { lifecycle_status: "archived", can_restore: true },
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
      management: {
        lifecycle_status: "active", can_delete: false, can_archive: true,
        can_restore: false, history_count: 2, active_run_count: 0,
        reason: "已产生运行证据，只能归档",
      },
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

  it("loads a selected pool's date reference lazily without inventing study dates", async () => {
    const pool = { pool_id: "pool_1", name: "One day", status: "active", current_snapshot_id: "snapshot_1" };
    const reference = { pool_id: "pool_1", stock_pool_snapshot_id: "snapshot_1", state: "observed_bounds",
      member_count: 1, members_with_data: 1, minimum_rows_per_member: 1,
      observed_start_date: "20261113", observed_end_date: "20261113", reference_only: true,
      continuous_history_verified: false, training_readiness_verified: false, recommended_dates: null };
    getMLOptions.mockImplementation(async (id?: string) => ({
      schema_version: "ml-options.v1", tasks: [], pools: [pool],
      ...(id ? { selected_pool_data_reference: reference } : {}),
    }));
    const wrapper = shallowMount(MLResearchWorkbench);
    await flushPromises();
    expect(getMLOptions).toHaveBeenCalledTimes(1);
    const vm = wrapper.vm as any;
    vm.showCreate = true; await flushPromises();
    expect(getMLOptions).toHaveBeenLastCalledWith("pool_1", 5);
    expect(vm.poolReferenceMessage).toContain("2026-11-13");
    expect(vm.poolReferenceMessage).toContain("无法据此推荐");
    expect(vm.form.train_start).toBe("");
    Object.assign(vm.form, { train_start: "2025-01-01", train_end: "2025-03-01",
      validation_start: "2025-03-02", validation_end: "2025-04-01",
      prediction_start: "2025-04-02", prediction_end: "2025-05-01" });
    expect(vm.datesOutsideReference).toBe(true);
    expect(vm.dateWindowError).toBe(""); // Planning is allowed before data preparation.
    expect(createMLStrategy).not.toHaveBeenCalled(); expect(createTask).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("offers compatible dates as an explicit action and leaves advanced modes manual", async () => {
    const pool = optionsWithDateRecommendation("pool_1", "snapshot_1", 5, "2024");
    getMLOptions.mockImplementation(async (id?: string, horizon?: number) => id
      ? optionsWithDateRecommendation(id, "snapshot_1", horizon ?? 5, "2024")
      : { schema_version: "ml-options.v1", tasks: [], pools: pool.pools });
    const wrapper = shallowMount(MLResearchWorkbench);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.showCreate = true;
    await flushPromises();

    expect(getMLOptions).toHaveBeenLastCalledWith("pool_1", 5);
    expect(vm.form.train_start).toBe("");
    expect(vm.form.train_end).toBe("");
    expect(vm.form.validation_start).toBe("");
    expect(vm.form.validation_end).toBe("");
    expect(vm.form.prediction_start).toBe("");
    expect(vm.form.prediction_end).toBe("");
    expect(vm.canApplyRecommendedDates).toBe(true);
    expect(vm.recommendationMessage).toContain("训练 60、验证 10、预测 5");
    expect(vm.recommendationMessage).toContain("条样本");
    expect(vm.recommendationMessage).toContain("不代表全部历史连续、训练已就绪或模型质量已验证");

    vm.form.mode = "walk_forward";
    await flushPromises();
    expect(vm.canApplyRecommendedDates).toBe(false);
    expect(vm.recommendationMessage).toContain("只适用于单模型入门模式");
    expect(wrapper.find('[data-testid="ml-apply-recommended-dates"]').exists()).toBe(false);
    vm.applyRecommendedDates();
    expect(vm.form.train_start).toBe("");

    vm.form.mode = "compatible";
    await flushPromises();
    expect(vm.canApplyRecommendedDates).toBe(true);
    await wrapper.get('[data-testid="ml-apply-recommended-dates"]').trigger("click");
    expect(vm.form.train_start).toBe("2024-01-02");
    expect(vm.form.train_end).toBe("2024-02-16");
    expect(vm.form.validation_start).toBe("2024-02-19");
    expect(vm.form.validation_end).toBe("2024-02-28");
    expect(vm.form.prediction_start).toBe("2024-03-03");
    expect(vm.form.prediction_end).toBe("2024-03-14");
    const verifiedRecommendation = vm.poolRecommendation;
    for (const unverified of [
      { continuous_history_verified: false },
      { minimum_samples_verified: false },
    ]) {
      vm.poolRecommendation = { ...verifiedRecommendation, ...unverified };
      await flushPromises();
      expect(vm.canApplyRecommendedDates).toBe(false);
      expect(wrapper.find('[data-testid="ml-apply-recommended-dates"]').exists()).toBe(false);
    }
    vm.poolRecommendation = verifiedRecommendation;
    await flushPromises();
    vm.poolRecommendation = { ...vm.poolRecommendation, state: "unavailable", reason: "calendar_incomplete" };
    vm.poolRecommendedDates = null;
    await flushPromises();
    expect(vm.canApplyRecommendedDates).toBe(false);
    expect(wrapper.find('[data-testid="ml-apply-recommended-dates"]').exists()).toBe(false);
    expect(vm.poolReferenceMessage).toContain("交易日历不完整");
    vm.poolRecommendation = { ...vm.poolRecommendation, reason: "data_not_ready" };
    expect(vm.poolReferenceMessage).toContain("准备或更新数据");
    vm.poolRecommendation = { ...vm.poolRecommendation, reason: "insufficient_samples" };
    expect(vm.poolReferenceMessage).toContain("不足以安排最小训练、验证和预测样本");
    expect(createMLStrategy).not.toHaveBeenCalled();
    expect(createTask).not.toHaveBeenCalled();
    expect(createMLTraining).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("discards a date reference after switching pools or snapshot versions", async () => {
    const pools = [
      { pool_id: "pool_1", status: "active", current_snapshot_id: "snapshot_1" },
      { pool_id: "pool_2", status: "active", current_snapshot_id: "snapshot_2" },
    ];
    let resolveOld: (value: unknown) => void = () => undefined;
    getMLOptions.mockImplementation((id?: string, horizon?: number) => {
      if (id === "pool_1") return new Promise(resolve => { resolveOld = resolve; });
      if (id === "pool_2") return Promise.resolve({
        ...optionsWithDateRecommendation("pool_2", "snapshot_2", horizon ?? 5, "2025"), pools,
      });
      return Promise.resolve({ schema_version: "ml-options.v1", tasks: [], pools });
    });
    const wrapper = shallowMount(MLResearchWorkbench); await flushPromises();
    const vm = wrapper.vm as any; vm.showCreate = true; await flushPromises();
    vm.form.pool_id = "pool_2"; await flushPromises();
    expect(vm.poolDataReference.pool_id).toBe("pool_2");
    expect(vm.poolRecommendation.horizon_sessions).toBe(5);
    expect(vm.poolRecommendedDates.train_start).toBe("20250102");
    resolveOld(optionsWithDateRecommendation("pool_1", "snapshot_1", 5, "2024"));
    await flushPromises();
    expect(vm.poolDataReference.pool_id).toBe("pool_2");
    expect(vm.poolRecommendedDates.train_start).toBe("20250102");
    vm.options.pools[1].current_snapshot_id = "snapshot_new"; await flushPromises();
    expect(vm.poolDataReference).toBeNull(); expect(vm.poolRecommendation).toBeNull(); expect(vm.poolReferenceError).toContain("版本");
    wrapper.unmount();
  });

  it("discards an earlier recommendation when the prediction horizon changes", async () => {
    const initial = optionsWithDateRecommendation("pool_1", "snapshot_1", 5, "2024");
    let resolveOld: (value: unknown) => void = () => undefined;
    getMLOptions.mockImplementation((id?: string, horizon?: number) => {
      if (!id) return Promise.resolve({ schema_version: "ml-options.v1", tasks: [], pools: initial.pools });
      if (horizon === 5) return new Promise(resolve => { resolveOld = resolve; });
      return Promise.resolve(optionsWithDateRecommendation(id, "snapshot_1", horizon ?? 10, "2025"));
    });
    const wrapper = shallowMount(MLResearchWorkbench);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.showCreate = true;
    await flushPromises();
    expect(getMLOptions).toHaveBeenLastCalledWith("pool_1", 5);

    vm.form.horizon = 10;
    await flushPromises();
    expect(getMLOptions).toHaveBeenLastCalledWith("pool_1", 10);
    expect(vm.poolRecommendation.horizon_sessions).toBe(10);
    expect(vm.poolRecommendedDates.train_start).toBe("20250102");

    resolveOld(optionsWithDateRecommendation("pool_1", "snapshot_1", 5, "2024"));
    await flushPromises();
    expect(vm.poolRecommendation.horizon_sessions).toBe(10);
    expect(vm.poolRecommendedDates.train_start).toBe("20250102");
    wrapper.unmount();
  });

  it("invalidates a pending recommendation when the create dialog closes and reopens", async () => {
    const initial = optionsWithDateRecommendation("pool_1", "snapshot_1", 5, "2024");
    let resolveOld: (value: unknown) => void = () => undefined;
    let selectedRequests = 0;
    getMLOptions.mockImplementation((id?: string, horizon?: number) => {
      if (!id) return Promise.resolve({ schema_version: "ml-options.v1", tasks: [], pools: initial.pools });
      selectedRequests += 1;
      if (selectedRequests === 1) return new Promise(resolve => { resolveOld = resolve; });
      return Promise.resolve(optionsWithDateRecommendation(id, "snapshot_1", horizon ?? 5, "2025"));
    });
    const wrapper = shallowMount(MLResearchWorkbench);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.showCreate = true;
    await flushPromises();
    expect(selectedRequests).toBe(1);

    vm.showCreate = false;
    vm.showCreate = true;
    await flushPromises();
    expect(selectedRequests).toBe(2);
    expect(vm.poolRecommendation.horizon_sessions).toBe(5);
    expect(vm.poolRecommendedDates.train_start).toBe("20250102");
    resolveOld(optionsWithDateRecommendation("pool_1", "snapshot_1", 5, "2024"));
    await flushPromises();
    expect(vm.poolRecommendedDates.train_start).toBe("20250102");
    expect(vm.canApplyRecommendedDates).toBe(true);
    wrapper.unmount();
  });

  it("discards a pending recommendation after the signed-in workspace changes", async () => {
    const initial = optionsWithDateRecommendation("pool_1", "snapshot_1", 5, "2024");
    const pending: Array<(value: unknown) => void> = [];
    getMLOptions.mockImplementation((id?: string) => {
      if (!id) return Promise.resolve({ schema_version: "ml-options.v1", tasks: [], pools: initial.pools });
      return new Promise(resolve => { pending.push(resolve); });
    });
    const wrapper = shallowMount(MLResearchWorkbench);
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.showCreate = true;
    await flushPromises();
    expect(pending.length).toBeGreaterThan(0);

    useAuthStore().setUser({ subject: "bob", workspace: { workspace_id: "workspace-bob" } } as any);
    await flushPromises();
    pending.forEach(resolve => resolve(optionsWithDateRecommendation("pool_1", "snapshot_1", 5, "2024")));
    await flushPromises();
    expect(vm.poolDataReference).toBeNull();
    expect(vm.poolRecommendation).toBeNull();
    expect(vm.poolRecommendedDates).toBeNull();
    wrapper.unmount();
  });

  it("requires user-selected date windows before saving a study", async () => {
    const wrapper = shallowMount(MLResearchWorkbench);
    await flushPromises();
    const vm = wrapper.vm as any;
    expect(vm.form.train_start).toBe("");
    expect(vm.form.prediction_start).toBe("");
    expect(vm.dateWindowError).toContain("请选择训练、验证和预测");

    await vm.saveStrategy();
    expect(createTask).not.toHaveBeenCalled();
    expect(createMLStrategy).not.toHaveBeenCalled();

    Object.assign(vm.form, {
      train_start: "2024-01-01", train_end: "2024-02-01",
      validation_start: "2024-02-02", validation_end: "2024-03-01",
      prediction_start: "2024-03-02", prediction_end: "2024-04-01",
    });
    expect(vm.dateWindowError).toBe("");
    vm.form.validation_start = "2024-01-15";
    expect(vm.dateWindowError).toContain("区间不能重叠");
    wrapper.unmount();
  });

  it("loads detail and paged prediction rows only after explicit selection", async () => {
    const wrapper = shallowMount(MLResearchWorkbench);
    await flushPromises();

    expect(wrapper.text()).not.toContain("批准并开始训练");

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

    const first = vm.startTraining();
    const second = vm.startTraining();
    expect(confirmTraining).toHaveBeenCalledTimes(1);
    resolveConfirmation("confirm");
    await Promise.all([first, second]);

    expect(createMLTraining).toHaveBeenCalledTimes(1);
    expect(createMLTraining.mock.calls[0][1]).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("creates only a typed approval request when the ML version has no approval", async () => {
    const taskId = `task_${"2".repeat(32)}`;
    const artifactId = `artifact_${"b".repeat(32)}`;
    getMLOptions.mockResolvedValueOnce({ schema_version: "ml-options.v1", tasks: [], pools: [
      { pool_id: "pool_1", name: "沪深300", status: "active", current_snapshot_id: "snapshot_1", member_count: 300 },
    ] });
    getMLStudy.mockResolvedValueOnce({
      schema_version: "ml-product-study-detail.v1",
      study: {
        artifact_id: artifactId, task_id: taskId, kind: "ml_strategy_version",
        status: "validated", content: { name: "测试模型", schema_version: "ml-strategy-version.v1" },
      },
      approval_artifact_id: null,
      management: { lifecycle_status: "active", can_delete: false, can_archive: true,
        can_restore: false, history_count: 2, active_run_count: 0, reason: "已产生运行证据，只能归档" },
      tasks: [{ task_id: taskId, title: "模型研究" }], artifacts: [],
      training_runs: { total: 0, runs: [] }, prediction_runs: { total: 0, runs: [] }, backtests: { total: 0, backtests: [] },
    });
    submitProductApprovalRequestOnce.mockResolvedValue({
      reconciled: false,
      request: {
        request_id: `approval_request_${"2".repeat(32)}`, request_type: "ml_strategy_version", status: "pending",
        owner_principal: "alice", workspace_id: "workspace-alice", task_id: taskId,
        resource_artifact_id: artifactId, content_sha256: "c".repeat(64), request_key: "00000000-0000-4000-8000-000000000005",
        created_at: "2026-10-14T00:00:00Z", updated_at: "2026-10-14T00:00:00Z",
        ml_strategy_artifact_id: artifactId,
      },
    });
    const wrapper = shallowMount(MLResearchWorkbench);
    await flushPromises();
    const vm = wrapper.vm as any;
    await vm.selectStudy(artifactId);
    vm.form.pool_id = "pool_1";
    await vm.startTraining();

    expect(submitProductApprovalRequestOnce).toHaveBeenCalledWith(
      { ownerPrincipal: "alice", workspaceId: "workspace-alice" },
      {
        schema_version: "byq-product-approval-request.v1",
        request_type: "ml_strategy_version",
        task_id: taskId,
        ml_strategy_artifact_id: artifactId,
      },
    );
    expect(createMLTraining).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("deletes a never-executed study after confirmation and refreshes the catalog", async () => {
    getMLStudy.mockResolvedValueOnce({
      schema_version: "ml-product-study-detail.v1",
      study: {
        artifact_id: "artifact_strategy", task_id: "task_1", kind: "ml_strategy_version",
        status: "validated", content: { name: "待删除研究", schema_version: "ml-strategy-version.v2" },
      },
      approval_artifact_id: "artifact_approval",
      management: {
        lifecycle_status: "active", can_delete: true, can_archive: false,
        can_restore: false, history_count: 0, active_run_count: 0,
        reason: "尚未执行，可删除",
      },
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

  it("restores an unconfirmed submission and only reads its original receipt", async () => {
    getMLOptions.mockResolvedValue({ schema_version: "ml-options.v1", tasks: [], pools: [
      { pool_id: "pool_1", name: "Synthetic", status: "active", current_snapshot_id: "snapshot_1", member_count: 1 },
    ] });
    localStorage.setItem("byq:ml-training:alice:workspace-alice:task_1:artifact_strategy:snapshot_1", "original-training-key");
    const wrapper = shallowMount(MLResearchWorkbench);
    await flushPromises();
    const vm = wrapper.vm as any;
    await vm.selectStudy("artifact_strategy");
    await vm.startTraining();
    expect(getMLTrainingSubmission).toHaveBeenCalledWith("original-training-key");
    expect(createMLTraining).not.toHaveBeenCalled();
    expect(confirmTraining).not.toHaveBeenCalled();
    expect(vm.receiptWatch.state).toBe("awaiting_receipt");
    expect(vm.next.label).toBe("核对原提交");
    await vm.reconcileOriginalSubmission();
    const reads = getMLTrainingSubmission.mock.calls.length;
    localStorage.clear(); sessionStorage.clear();
    await vm.reconcileOriginalSubmission();
    await vm.startTraining();
    expect(getMLTrainingSubmission).toHaveBeenCalledTimes(reads);
    expect(createMLTraining).not.toHaveBeenCalled();
    expect(confirmTraining).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("does not apply a training confirmation to a newly selected pool", async () => {
    getMLOptions.mockResolvedValue({ schema_version: "ml-options.v1", tasks: [], pools: [
      { pool_id: "pool_1", name: "Original", status: "active", current_snapshot_id: "snapshot_1", member_count: 1 },
      { pool_id: "pool_2", name: "Other", status: "active", current_snapshot_id: "snapshot_2", member_count: 1 },
    ] });
    let resolveConfirmation: (value: string) => void = () => undefined;
    confirmTraining.mockReturnValueOnce(new Promise(resolve => { resolveConfirmation = resolve; }));
    const wrapper = shallowMount(MLResearchWorkbench);
    await flushPromises();
    const vm = wrapper.vm as any;
    await vm.selectStudy("artifact_strategy");
    const started = vm.startTraining();
    vm.form.pool_id = "pool_2";
    resolveConfirmation("confirm");
    await started;
    expect(createMLTraining).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("does not let a late detail response replace the newly selected model study", async () => {
    const artifactA = `artifact_${"a".repeat(32)}`;
    const artifactB = `artifact_${"b".repeat(32)}`;
    const detailFor = (artifactId: string) => ({
      schema_version: "ml-product-study-detail.v1",
      study: { artifact_id: artifactId, task_id: `task_${"1".repeat(32)}`, kind: "ml_strategy_version",
        status: "validated", content: { name: artifactId, schema_version: "ml-strategy-version.v1" } },
      approval_artifact_id: null,
      management: { lifecycle_status: "active", can_delete: false, can_archive: true,
        can_restore: false, history_count: 0, active_run_count: 0, reason: "只读检查" },
      tasks: [], artifacts: [], training_runs: { total: 0, runs: [] },
      prediction_runs: { total: 0, runs: [] }, backtests: { total: 0, backtests: [] },
    });
    let resolveOld: (value: unknown) => void = () => undefined;
    getMLStudy.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }))
      .mockResolvedValueOnce(detailFor(artifactB));
    const wrapper = shallowMount(MLResearchWorkbench);
    await flushPromises();
    const vm = wrapper.vm as any;
    const oldSelection = vm.selectStudy(artifactA);
    const currentSelection = vm.selectStudy(artifactB);
    await currentSelection;
    resolveOld(detailFor(artifactA));
    await oldSelection;

    expect(vm.selectedStrategy).toBe(artifactB);
    expect(vm.detail.study.artifact_id).toBe(artifactB);
    wrapper.unmount();
  });

  it("archives an executed study and keeps deletion unavailable", async () => {
    const wrapper = shallowMount(MLResearchWorkbench);
    await flushPromises();
    const vm = wrapper.vm as any;
    await vm.selectStudy("artifact_strategy");
    expect(vm.canDeleteStudy).toBe(false);
    expect(vm.canArchiveStudy).toBe(true);

    await vm.changeStudyLifecycle("archived");

    expect(setMLStudyLifecycle).toHaveBeenCalledWith("artifact_strategy", "archived");
    expect(vm.selectedStrategy).toBe("");
    expect(getMLStudies).toHaveBeenCalledTimes(2);
  });
});
