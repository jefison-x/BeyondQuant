<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  approveMLStrategy, createMLPrediction, createMLStrategy, createMLTraining,
  deleteMLStudy,
  getMLCapabilities, getMLOptions, getMLPrediction, getMLPredictionRows,
  getMLStudies, getMLStudy, getMLTraining,
  type MLArtifact, type MLCapabilities, type MLCapabilityComponent, type MLRun,
  type MLOptions, type MLStudyDetail, type MLStudySummary,
} from "@/api/mlResearch";
import { createTask } from "@/api/research";
import { getBacktest, runBacktest, submitBacktest } from "@/api/quant";
import ManagementWorkspace from "@/components/layout/ManagementWorkspace.vue";
import ListFilterPagination from "@/components/ui/ListFilterPagination.vue";
import { formatChinaTime } from "@/time";
import { shortReference, statusLabel } from "@/display";
import { createRequestId } from "@/utils/requestId";

type StudyMode = "compatible" | "walk_forward" | "regime";
type ExpertDraft = { key: "risk_on" | "neutral" | "risk_off"; label: string; learner: string };

const router = useRouter();
const loading = ref(true), catalogLoading = ref(false), detailLoading = ref(false), busy = ref(false), deleting = ref(false);
const error = ref(""), showCreate = ref(false), activeTab = ref("overview");
const capabilities = ref<MLCapabilities | null>(null);
const options = ref<MLOptions>({ schema_version: "ml-options.v1", tasks: [], pools: [] });
const studies = ref<MLStudySummary[]>([]), studiesTotal = ref(0), catalogPage = ref(1);
const catalogQuery = ref(""), statusFilter = ref("all"), selectedStrategy = ref("");
const detail = ref<MLStudyDetail | null>(null);
const pageSize = 12;
let timer: number | undefined, catalogTimer: number | undefined;
let catalogRequest = 0, detailRequest = 0, predictionRowsRequest = 0;

const form = reactive({
  mode: "compatible" as StudyMode, capability_id: "", task_id: "", pool_id: "",
  name: "LightGBM 收益排序",
  train_start: "2026-01-01", train_end: "2026-02-19",
  validation_start: "2026-02-20", validation_end: "2026-03-11",
  development_start: "2025-10-01", development_end: "2026-02-28",
  prediction_start: "2026-03-12", prediction_end: "2026-03-30",
  feature_set: "", target: "", validation_plan: "", learner: "", portfolio_policy: "",
  regime_definition: "", routing_policy: "", fallback: "neutral",
  horizon: 5, top_n: 1, rebalance: "weekly", validation_mode: "expanding",
  train_sessions: 60, validation_sessions: 10, step_sessions: 10, folds: 2,
  purge_sessions: 5, embargo_sessions: 0, capital: 1_000_000, lot_size: 100,
});
const experts = reactive<ExpertDraft[]>([
  { key: "risk_on", label: "进取状态", learner: "" },
  { key: "neutral", label: "中性状态", learner: "" },
  { key: "risk_off", label: "防守状态", learner: "" },
]);

const registry = computed(() => capabilities.value?.registry.components ?? []);
const qualified = (kind: string) => registry.value.filter(item => item.kind === kind && item.status === "qualified");
const learners = computed(() => qualified("learner_profile"));
const featureSets = computed(() => qualified("feature_set"));
const targets = computed(() => qualified("target"));
const validations = computed(() => qualified("validation_plan"));
const portfolios = computed(() => qualified("portfolio_policy"));
const regimes = computed(() => qualified("regime_definition"));
const routers = computed(() => qualified("routing_policy"));
const legacyCapabilities = computed(() => capabilities.value?.capabilities ?? []);
const activePools = computed(() => options.value.pools.filter(pool => pool.status === "active" && pool.current_snapshot_id));
const chosenPool = computed(() => activePools.value.find(pool => pool.pool_id === form.pool_id));
const selected = computed(() => detail.value?.study ?? null);
const selectedSummary = computed(() => studies.value.find(item => item.artifact_id === selectedStrategy.value));
const content = computed<Record<string, any>>(() => selected.value?.content ?? {});
const training = ref<MLRun | null>(null), prediction = ref<MLRun | null>(null);
const backtest = ref<Record<string, any> | null>(null), selectedApproval = ref("");
const artifacts = computed(() => detail.value?.artifacts ?? []);
const artifact = (id?: string) => artifacts.value.find(item => item.artifact_id === id);
const model = computed(() => artifact(training.value?.model_artifact_id));
const expertModels = computed(() => artifacts.value.filter(item => item.kind === "ml_model" && item.content.expert_key));
const regimeSnapshot = computed(() => artifacts.value.find(item => item.kind === "ml_regime_snapshot"));
const signal = computed(() => artifact(prediction.value?.signal_artifact_id));
const isV2 = computed(() => content.value.schema_version === "ml-strategy-version.v2");
const isRegime = computed(() => Boolean(content.value.regime?.enabled));

const predictionRows = ref<Record<string, any>[]>([]), predictionRowsTotal = ref(0);
const predictionRowsLoading = ref(false), predictionRowsQuery = ref(""), predictionRowsPage = ref(1);
const predictionRowsPageSize = 50;
const predictionRunId = computed(() => prediction.value?.status === "completed" ? prediction.value.prediction_run_id ?? "" : "");
const trainingSubmissionCache = new Map<string, string>();

function trainingSubmissionStorageKey() {
  return selected.value && chosenPool.value
    ? `byq:ml-training:${selected.value.task_id}:${selected.value.artifact_id}:${chosenPool.value.current_snapshot_id}`
    : "";
}
function trainingSubmissionId() {
  const storageKey = trainingSubmissionStorageKey();
  if (!storageKey) return "";
  let existing = trainingSubmissionCache.get(storageKey) ?? "";
  try { existing ||= window.sessionStorage.getItem(storageKey) ?? ""; } catch { /* memory fallback */ }
  if (existing) return existing;
  const created = createRequestId();
  trainingSubmissionCache.set(storageKey, created);
  try { window.sessionStorage.setItem(storageKey, created); } catch { /* memory fallback */ }
  return created;
}
function clearTrainingSubmissionId() {
  const storageKey = trainingSubmissionStorageKey();
  if (!storageKey) return;
  trainingSubmissionCache.delete(storageKey);
  try { window.sessionStorage.removeItem(storageKey); } catch { /* memory fallback */ }
}

function componentLabel(item: MLCapabilityComponent) { return item.display_name || item.id; }
function initializeCapabilityDefaults() {
  form.capability_id ||= String(legacyCapabilities.value[0]?.capability_id ?? "");
  form.feature_set ||= String(featureSets.value[0]?.id ?? "");
  form.target ||= String(targets.value[0]?.id ?? "");
  form.validation_plan ||= String(validations.value.find(item => item.id.includes("walk-forward"))?.id ?? validations.value[0]?.id ?? "");
  form.learner ||= String(learners.value.find(item => item.id.includes("lightgbm"))?.id ?? learners.value[0]?.id ?? "");
  form.portfolio_policy ||= String(portfolios.value[0]?.id ?? "");
  form.regime_definition ||= String(regimes.value[0]?.id ?? "");
  form.routing_policy ||= String(routers.value[0]?.id ?? "");
  const ridge = String(learners.value.find(item => item.id.includes("ridge"))?.id ?? form.learner);
  const lightgbm = String(learners.value.find(item => item.id.includes("lightgbm"))?.id ?? form.learner);
  experts[0].learner ||= ridge; experts[1].learner ||= ridge; experts[2].learner ||= lightgbm;
}

function applyDetail(value: MLStudyDetail) {
  detail.value = value;
  training.value = value.training_runs.runs[0] ?? null;
  prediction.value = value.prediction_runs.runs[0] ?? null;
  backtest.value = value.backtests.backtests[0] ?? null;
  selectedApproval.value = String(value.approval_artifact_id ?? "");
}

async function loadCatalog() {
  const requestId = ++catalogRequest; catalogLoading.value = true;
  try {
    const page = await getMLStudies(catalogQuery.value, statusFilter.value, pageSize, (catalogPage.value - 1) * pageSize);
    if (requestId !== catalogRequest) return;
    studies.value = page.studies; studiesTotal.value = page.total;
    if (selectedStrategy.value && !page.studies.some(item => item.artifact_id === selectedStrategy.value)) {
      selectedStrategy.value = ""; detail.value = null;
    }
  } catch (e) {
    if (requestId === catalogRequest) error.value = e instanceof Error ? e.message : "模型研究目录加载失败";
  } finally { if (requestId === catalogRequest) catalogLoading.value = false; }
}

async function selectStudy(id: string) {
  selectedStrategy.value = id; activeTab.value = "overview";
  predictionRows.value = []; predictionRowsTotal.value = 0; predictionRowsPage.value = 1;
  const requestId = ++detailRequest; detailLoading.value = true; error.value = "";
  try {
    const value = await getMLStudy(id);
    if (requestId === detailRequest && selectedStrategy.value === id) applyDetail(value);
  } catch (e) {
    if (requestId === detailRequest) error.value = e instanceof Error ? e.message : "模型研究详情加载失败";
  } finally { if (requestId === detailRequest) detailLoading.value = false; }
}

async function refreshDetail() { if (selectedStrategy.value) await selectStudy(selectedStrategy.value); }
async function bootstrap() {
  loading.value = true; error.value = "";
  try {
    const [catalogue, choices] = await Promise.all([getMLCapabilities(), getMLOptions()]);
    capabilities.value = catalogue; options.value = choices; initializeCapabilityDefaults();
    form.task_id ||= String(choices.tasks[0]?.task_id ?? "");
    form.pool_id ||= String(activePools.value[0]?.pool_id ?? "");
    await loadCatalog();
  } catch (e) { error.value = e instanceof Error ? e.message : "模型研究加载失败"; }
  finally { loading.value = false; }
}

watch(catalogQuery, () => {
  catalogPage.value = 1;
  if (catalogTimer) clearTimeout(catalogTimer);
  catalogTimer = window.setTimeout(() => void loadCatalog(), 220);
});
watch(statusFilter, () => { catalogPage.value = 1; void loadCatalog(); });
watch(catalogPage, () => void loadCatalog());
watch(() => form.mode, mode => {
  if (mode === "compatible") form.name = "LightGBM 收益排序";
  if (mode === "walk_forward") form.name = "净化走步模型研究";
  if (mode === "regime") form.name = "沪深300市场状态专家模型";
});

async function loadPredictionRows() {
  const runId = predictionRunId.value, requestId = ++predictionRowsRequest;
  if (activeTab.value !== "prediction") return;
  if (!runId) { predictionRows.value = []; predictionRowsTotal.value = 0; return; }
  predictionRowsLoading.value = true;
  try {
    const result = await getMLPredictionRows(runId, predictionRowsQuery.value, predictionRowsPageSize, (predictionRowsPage.value - 1) * predictionRowsPageSize);
    if (requestId === predictionRowsRequest) { predictionRows.value = result.rows; predictionRowsTotal.value = result.total; }
  } catch (e) {
    if (requestId === predictionRowsRequest) error.value = e instanceof Error ? e.message : "预测结果加载失败";
  } finally { if (requestId === predictionRowsRequest) predictionRowsLoading.value = false; }
}
watch([predictionRowsQuery, predictionRowsPage], () => {
  if (activeTab.value !== "prediction") return;
  if (timer) clearTimeout(timer);
  timer = window.setTimeout(() => void loadPredictionRows(), 180);
});
watch(activeTab, tab => { if (tab === "prediction") void loadPredictionRows(); });

function buildStrategy() {
  if (form.mode === "compatible") {
    const capability = legacyCapabilities.value.find(item => item.capability_id === form.capability_id) ?? legacyCapabilities.value[0];
    if (!capability) throw new Error("兼容能力当前不可用");
    return {
      schema_version: "ml-strategy-version.v1", name: form.name,
      learner: capability.learner, feature_set: { id: capability.feature_set.id },
      target: { kind: "forward_return", horizon_sessions: form.horizon },
      split: {
        train: { start: form.train_start, end: form.train_end },
        validation: { start: form.validation_start, end: form.validation_end },
        prediction: { start: form.prediction_start, end: form.prediction_end },
      },
      learner_parameters: {},
      signal_policy: { kind: "top_n_equal_weight", top_n: form.top_n, rebalance: form.rebalance },
    };
  }
  const strategy: Record<string, any> = {
    schema_version: "ml-strategy-version.v2", name: form.name,
    feature_set: { id: form.feature_set, parameters: {} },
    target: { id: form.target, parameters: { horizon_sessions: form.horizon } },
    validation_plan: { id: form.validation_plan, parameters: {
      mode: form.validation_mode, train_sessions: form.train_sessions,
      validation_sessions: form.validation_sessions, step_sessions: form.step_sessions,
      folds: form.folds, purge_sessions: Math.max(form.purge_sessions, form.horizon),
      embargo_sessions: form.embargo_sessions,
    } },
    learner: { profile: form.learner, parameters: {} },
    portfolio_policy: { id: form.portfolio_policy, parameters: { top_n: form.top_n, rebalance: form.rebalance } },
    development_window: { start: form.development_start, end: form.development_end },
    prediction_window: { start: form.prediction_start, end: form.prediction_end },
  };
  if (form.mode === "regime") {
    strategy.regime = { definition: form.regime_definition, parameters: {}, enabled: true };
    strategy.routing_policy = { id: form.routing_policy, fallback: form.fallback };
    strategy.experts = experts.map(item => ({
      key: item.key, learner: { profile: item.learner, parameters: {} },
      training_regimes: ["risk_on", "neutral", "risk_off"],
    }));
    strategy.learner = { profile: experts.find(item => item.key === form.fallback)?.learner ?? form.learner, parameters: {} };
  }
  return strategy;
}

async function ensureTask() {
  if (!form.task_id) {
    const body: any = await createTask("模型收益排序研究", "验证可信训练、样本外预测、冻结信号与可复现回测");
    form.task_id = body.task_id ?? body.task?.task_id;
  }
}
async function saveStrategy() {
  busy.value = true;
  try {
    await ensureTask();
    const response = await createMLStrategy({ task_id: form.task_id, strategy: buildStrategy() });
    const id = String(response.artifact.artifact_id);
    showCreate.value = false; catalogPage.value = 1; catalogQuery.value = ""; statusFilter.value = "all";
    await loadCatalog(); await selectStudy(id);
    ElMessage.success("研究定义已冻结，可以进入训练");
  } catch (e) { ElMessage.error(e instanceof Error ? e.message : "研究定义保存失败"); }
  finally { busy.value = false; }
}
const canDeleteStudy = computed(() => Boolean(
  detail.value
  && detail.value.training_runs.total === 0
  && detail.value.prediction_runs.total === 0
  && detail.value.backtests.total === 0
));
async function removeStudy() {
  if (!selected.value || !canDeleteStudy.value || deleting.value) return;
  const artifactId = selected.value.artifact_id;
  const name = String(content.value.name || "未命名模型研究");
  deleting.value = true;
  try {
    await ElMessageBox.confirm(
      `删除“${name}”后，它将从研究目录隐藏，相关审批也会失效。`,
      "删除未执行的模型研究",
      { type: "warning", confirmButtonText: "删除研究", cancelButtonText: "取消" },
    );
    await deleteMLStudy(artifactId);
    selectedStrategy.value = "";
    detail.value = null;
    training.value = null;
    prediction.value = null;
    backtest.value = null;
    selectedApproval.value = "";
    await loadCatalog();
    ElMessage.success("模型研究已删除；审计记录已保留");
  } catch (e) {
    if (e !== "cancel" && e !== "close") {
      ElMessage.error(e instanceof Error ? e.message : "模型研究删除失败");
    }
  } finally {
    deleting.value = false;
  }
}
async function approveAndTrain() {
  // Acquire the UI latch before opening the asynchronous confirmation. A
  // rapid double click must never create two independent confirmation flows.
  if (busy.value || deleting.value || !selected.value || !chosenPool.value) return;
  busy.value = true;
  try {
    await ElMessageBox.confirm(`将使用“${chosenPool.value.name}”的当前冻结快照开始训练。`, "确认训练范围", { type: "warning", confirmButtonText: "批准并开始训练", cancelButtonText: "返回检查" });
    if (!selectedApproval.value) {
      const approved = await approveMLStrategy({ task_id: selected.value.task_id, ml_strategy_artifact_id: selected.value.artifact_id, decision: "approved", rationale: "用户在模型研究工作台确认范围并批准训练" });
      selectedApproval.value = approved.artifact.artifact_id;
    }
    const submissionId = trainingSubmissionId();
    training.value = (await createMLTraining(
      { task_id: selected.value.task_id, ml_strategy_artifact_id: selected.value.artifact_id, stock_pool_snapshot_id: chosenPool.value.current_snapshot_id },
      submissionId,
    )).training_run;
    clearTrainingSubmissionId();
    ElMessage.success("训练已提交；页面与小巴下次会话会读取同一持久状态"); pollTraining();
  } catch (e) {
    if (e !== "cancel" && e !== "close") ElMessage.error(e instanceof Error ? e.message : "训练提交失败；再次提交会自动对账，不会重复创建");
  }
  finally { busy.value = false; }
}
function pollTraining() {
  if (!training.value?.training_run_id || ["completed", "failed", "cancelled"].includes(training.value.status)) { void refreshDetail().then(loadCatalog); return; }
  timer = window.setTimeout(async () => {
    try { training.value = (await getMLTraining(training.value!.training_run_id!)).training_run; pollTraining(); }
    catch { void refreshDetail(); }
  }, 1200);
}
async function predict() {
  if (!training.value?.model_artifact_id || !selectedApproval.value || !selected.value) return;
  busy.value = true;
  try {
    prediction.value = (await createMLPrediction({ task_id: selected.value.task_id, model_artifact_id: training.value.model_artifact_id, approval_artifact_id: selectedApproval.value, execution: { initial_capital: form.capital, lot_size: form.lot_size } })).prediction_run;
    ElMessage.success("样本外预测已提交"); pollPrediction();
  } catch (e) { ElMessage.error(e instanceof Error ? e.message : "预测失败"); }
  finally { busy.value = false; }
}
function pollPrediction() {
  if (!prediction.value?.prediction_run_id || ["completed", "failed", "cancelled"].includes(prediction.value.status)) { void refreshDetail().then(loadCatalog); return; }
  timer = window.setTimeout(async () => {
    try { prediction.value = (await getMLPrediction(prediction.value!.prediction_run_id!)).prediction_run; pollPrediction(); }
    catch { void refreshDetail(); }
  }, 1200);
}
async function backtestSignal() {
  if (!prediction.value?.signal_artifact_id || !selected.value || !selectedApproval.value) return;
  busy.value = true;
  try {
    const nonce = `ml-ui-${Date.now()}`;
    const made: any = await submitBacktest({ task_id: selected.value.task_id, strategy_version_artifact_id: selected.value.artifact_id, approval_artifact_id: selectedApproval.value, signal_snapshot_artifact_id: prediction.value.signal_artifact_id, trace_id: nonce, idempotency_key: nonce }, "");
    const id = made.job.job_id; backtest.value = await runBacktest(id, ""); ElMessage.success("回测已提交");
    const watchJob = async () => { const job: any = await getBacktest(id, ""); backtest.value = job; if (!["completed", "failed", "cancelled"].includes(job.status)) timer = window.setTimeout(watchJob, 1200); else { await refreshDetail(); await loadCatalog(); } };
    void watchJob();
  } catch (e) { ElMessage.error(e instanceof Error ? e.message : "回测失败"); }
  finally { busy.value = false; }
}

function stepState(value: Record<string, any> | MLRun | null) { return !value ? "pending" : value.status === "completed" ? "completed" : ["failed", "cancelled"].includes(value.status) ? "failed" : "active"; }
const steps = computed(() => [
  { label: "研究定义", hint: "范围与方法已冻结", state: selected.value ? "completed" : "pending" },
  { label: "训练验证", hint: isV2.value ? "净化走步验证" : "训练集与验证集隔离", state: stepState(training.value) },
  { label: "预测与信号", hint: isRegime.value ? "按冻结市场状态路由" : "只使用样本外数据", state: stepState(prediction.value) },
  { label: "回测复核", hint: "复用冻结信号", state: stepState(backtest.value) },
]);
const next = computed(() => {
  if (!selected.value) return { title: "选择或创建一项模型研究", hint: "目录与详情分开加载，首屏不会下载历史大制品。", action: "create", label: "新建模型研究" };
  if (!training.value || ["failed", "cancelled"].includes(training.value.status)) return { title: "批准研究并开始训练", hint: "确认冻结股票池后，在可信计算环境中训练。", action: "train", label: training.value ? "重新开始训练" : "批准并开始训练" };
  if (training.value.status !== "completed") return { title: "模型正在训练", hint: "完成后即可生成样本外预测。", action: "wait", label: "训练进行中" };
  if (!prediction.value || ["failed", "cancelled"].includes(prediction.value.status)) return { title: "生成样本外预测", hint: isRegime.value ? "每个交易日按冻结的沪深300状态选择专家。" : "使用已验证模型生成排名和冻结信号。", action: "predict", label: prediction.value ? "重新生成预测" : "生成预测与信号" };
  if (prediction.value.status !== "completed") return { title: "正在生成预测与信号", hint: "系统正在完成排名与信号冻结。", action: "wait", label: "预测进行中" };
  if (!backtest.value || ["failed", "cancelled"].includes(String(backtest.value.status))) return { title: "用回测复核研究结论", hint: "回测不会重新训练或改变模型路由。", action: "backtest", label: "提交并运行回测" };
  if (backtest.value.status !== "completed") return { title: "回测正在运行", hint: "完成后可查看完整收益与成交证据。", action: "wait", label: "回测进行中" };
  return { title: "研究闭环已完成", hint: "模型、预测、信号和回测结果均已留存。", action: "view", label: "查看完整回测" };
});
function runNext() {
  if (next.value.action === "create") showCreate.value = true;
  else if (next.value.action === "train") void approveAndTrain();
  else if (next.value.action === "predict") void predict();
  else if (next.value.action === "backtest") void backtestSignal();
  else if (next.value.action === "view" && backtest.value?.job_id) void router.push({ path: "/backtest", query: { job: String(backtest.value.job_id) } });
}

const STAGES: Record<string, string> = { definition: "待训练", training: "训练中", model: "模型已就绪", prediction: "预测中", signal: "信号已就绪", backtest: "回测中", completed: "已完成", failed: "需处理" };
const methodLabel = (value: MLStudySummary | MLArtifact | null) => {
  const source: any = value && "content" in value ? value.content : value;
  if (source?.regime_enabled || source?.regime?.enabled) return "沪深300状态专家";
  const profile = source?.learner_profile ?? source?.learner?.profile;
  const label = learners.value.find(item => item.id === profile)?.display_name ?? profile ?? "模型";
  return source?.schema_version === "ml-strategy-version.v1" ? `${label} · 单次验证` : `${label} · 净化走步`;
};
const selectedPool = computed(() => options.value.pools.find(pool => pool.current_snapshot_id === training.value?.stock_pool_snapshot_id) ?? chosenPool.value ?? null);
const metric = (value: unknown, digits = 4) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "-";
const period = (value: any) => value?.start && value?.end ? `${value.start} 至 ${value.end}` : "-";
const rebalance = (value: unknown) => ({ daily: "每日", weekly: "每周", monthly: "每月" } as Record<string, string>)[String(value)] ?? "-";
const portfolio = computed(() => isV2.value ? content.value.portfolio_policy?.parameters : content.value.signal_policy);
const targetHorizon = computed(() => isV2.value ? content.value.target?.parameters?.horizon_sessions : content.value.target?.horizon_sessions);
const foldMetrics = computed(() => model.value?.content.metrics ?? expertModels.value[0]?.content.metrics ?? {});

onMounted(bootstrap);
onBeforeUnmount(() => { if (timer) clearTimeout(timer); if (catalogTimer) clearTimeout(catalogTimer); });
</script>

<template>
<section class="ml-workbench">
  <div v-if="loading" class="base-loading" role="status">加载模型研究能力与目录...</div>
  <div v-else-if="error && !capabilities" class="base-error" role="alert">{{ error }} <el-button link @click="bootstrap">重试</el-button></div>
  <ManagementWorkspace v-else eyebrow="核心研究资产" title="模型研究目录与实验进程" description="从研究定义、可信训练和样本外预测，逐步推进到冻结信号与可复现回测。" catalog-label="模型研究" :count="studiesTotal" @return="router.push('/agent')">
    <template #return>返回投研对话</template>
    <template #actions><el-button :loading="catalogLoading" @click="loadCatalog">刷新</el-button><el-button type="primary" @click="showCreate = true">新建模型研究</el-button></template>
    <template #summary>能力来自运行时注册表；目录与详情均按需加载</template>
    <template #catalog>
      <el-card shadow="never" class="research-catalog"><template #header><div class="card-heading"><span class="card-title">研究目录</span><small class="card-sub">服务端筛选与分页</small></div></template>
        <ListFilterPagination v-model:query="catalogQuery" v-model:page="catalogPage" :page-size="pageSize" :total="studiesTotal" placeholder="搜索研究名称或任务" label="模型研究分页">
          <template #filters><el-select v-model="statusFilter" aria-label="模型研究状态" style="width:130px"><el-option label="全部状态" value="all"/><el-option label="进行中" value="active"/><el-option label="已完成" value="completed"/><el-option label="需处理" value="failed"/></el-select></template>
          <div v-if="catalogLoading" class="base-loading" role="status">加载目录...</div>
          <el-empty v-else-if="!studies.length" description="暂无模型研究"><el-button type="primary" @click="showCreate = true">创建第一项研究</el-button></el-empty>
          <div v-else class="research-list"><button v-for="item in studies" :key="item.artifact_id" type="button" class="research-list-item" :class="{active:item.artifact_id===selectedStrategy}" :aria-pressed="item.artifact_id===selectedStrategy" @click="selectStudy(item.artifact_id)"><span class="list-head"><strong>{{ item.name || '未命名模型研究' }}</strong><el-tag size="small" :type="item.stage==='completed'?'success':item.stage==='failed'?'danger':'info'">{{ STAGES[item.stage] ?? item.stage }}</el-tag></span><span class="method">{{ methodLabel(item) }}</span><span class="list-meta"><span>{{ item.task_title }}</span><time>{{ formatChinaTime(item.created_at) }}</time></span></button></div>
        </ListFilterPagination>
      </el-card>
    </template>
    <template #detail>
      <el-card v-if="detailLoading" shadow="never"><div class="base-loading" role="status">按需加载研究详情...</div></el-card>
      <el-card v-else-if="selected" shadow="never" class="research-detail"><template #header><div class="detail-heading"><div><span>{{ methodLabel(selected) }}</span><h3>{{ content.name || '未命名模型研究' }}</h3><p>{{ selectedSummary?.task_title }}</p></div><div class="detail-actions"><el-tag :type="backtest?.status==='completed'?'success':'info'">{{ STAGES[selectedSummary?.stage ?? 'definition'] }}</el-tag><el-tooltip :content="canDeleteStudy?'删除未执行的研究':'已有训练、预测或回测记录，需保留审计证据'" placement="bottom"><span><el-button type="danger" plain size="small" :disabled="!canDeleteStudy||busy" :loading="deleting" data-testid="ml-delete" @click="removeStudy">删除</el-button></span></el-tooltip></div></div></template>
        <ol class="pipeline" aria-label="模型研究进度"><li v-for="(step,index) in steps" :key="step.label" :class="`is-${step.state}`"><b>{{ step.state==='completed'?'✓':index+1 }}</b><span><strong>{{ step.label }}</strong><small>{{ step.hint }}</small></span></li></ol>
        <section class="next-step"><div><span>建议下一步</span><strong>{{ next.title }}</strong><p>{{ next.hint }}</p></div><div class="next-actions"><el-select v-if="next.action==='train'" v-model="form.pool_id" aria-label="训练使用的冻结股票池" data-testid="ml-pool" placeholder="选择冻结股票池"><el-option v-for="pool in activePools" :key="pool.pool_id" :label="`${pool.name} · ${pool.member_count}只`" :value="pool.pool_id"/></el-select><el-button type="primary" :disabled="next.action==='wait'||(next.action==='train'&&!chosenPool)" :loading="busy" :data-testid="next.action==='train'?'ml-train':next.action==='predict'?'ml-predict':next.action==='backtest'?'ml-backtest':undefined" @click="runNext">{{ next.label }}</el-button></div></section>
        <el-tabs v-model="activeTab" class="research-tabs">
          <el-tab-pane label="研究概览" name="overview"><div class="summary-grid"><div><span>研究方法</span><strong>{{ methodLabel(selected) }}</strong><small>{{ isV2?'净化走步验证':'兼容单次验证' }}</small></div><div><span>研究范围</span><strong>{{ selectedPool?.name || '训练时选择股票池' }}</strong><small>{{ selectedPool?`${selectedPool.member_count} 只股票`:'使用不可变成员快照' }}</small></div><div><span>预测目标</span><strong>未来 {{ targetHorizon ?? form.horizon }} 个交易日收益</strong><small>样本外预测不包含标签</small></div><div><span>组合规则</span><strong>前 {{ portfolio?.top_n ?? form.top_n }} 名等权</strong><small>{{ rebalance(portfolio?.rebalance ?? form.rebalance) }}调仓</small></div></div>
            <section class="content-section"><h4>数据与验证时间窗</h4><p>{{ isV2?'开发区间内生成有净化间隔的走步折；预测区间位于所有模型选择之后。':'训练、验证和预测按时间先后隔离。' }}</p><dl class="periods" :class="{two:isV2}"><template v-if="isV2"><div><dt>开发与走步验证</dt><dd>{{ period(content.development_window) }}</dd></div><div><dt>生成样本外预测</dt><dd>{{ period(content.prediction_window) }}</dd></div></template><template v-else><div><dt>学习历史规律</dt><dd>{{ period(content.split?.train) }}</dd></div><div><dt>验证模型表现</dt><dd>{{ period(content.split?.validation) }}</dd></div><div><dt>生成样本外预测</dt><dd>{{ period(content.split?.prediction) }}</dd></div></template></dl></section>
            <section v-if="isRegime" class="content-section"><h4>市场状态专家路由</h4><p>状态只由冻结的沪深300当日及历史行情判定；证据不足时使用已批准的后备专家。</p><div class="expert-grid"><article v-for="expert in content.experts" :key="expert.key"><strong>{{ ({risk_on:'进取',neutral:'中性',risk_off:'防守'} as Record<string,string>)[expert.key] }}</strong><span>{{ learners.find(item=>item.id===expert.learner.profile)?.display_name ?? expert.learner.profile }}</span><small>训练状态：{{ expert.training_regimes.join('、') }}</small></article></div><div v-if="regimeSnapshot" class="regime-counts"><span>沪深300 · 60 日暖机</span><el-tag v-for="(count,state) in regimeSnapshot.content.counts" :key="state" size="small">{{ state }} {{ count }}</el-tag></div></section>
            <section v-if="model" class="content-section"><h4>训练结果</h4><p>指标来自验证折，不代表未来收益承诺。</p><div class="metrics"><div><span>验证误差 RMSE</span><strong>{{ metric(foldMetrics.validation_rmse ?? foldMetrics.validation_rmse_mean,6) }}</strong></div><div><span>排序相关 Rank IC</span><strong>{{ metric(foldMetrics.validation_rank_ic ?? foldMetrics.validation_rank_ic_mean) }}</strong></div><div><span>有效验证折</span><strong>{{ model.content.folds?.length ?? expertModels[0]?.content.folds?.length ?? '-' }}</strong></div><div><span>训练模型</span><strong>{{ isRegime?expertModels.length:1 }}</strong></div></div></section>
          </el-tab-pane>
          <el-tab-pane label="预测结果" name="prediction"><div v-if="predictionRowsLoading" class="base-loading" role="status">加载预测排名...</div><el-empty v-else-if="!predictionRowsTotal" description="完成训练后可在这里查看样本外排名"/><template v-else><div class="result-intro"><div><strong>样本外排名</strong><span>共 {{ predictionRowsTotal }} 条记录</span></div><el-tag v-if="signal" type="success">冻结信号已生成</el-tag></div><ListFilterPagination v-model:query="predictionRowsQuery" v-model:page="predictionRowsPage" :page-size="predictionRowsPageSize" :total="predictionRowsTotal" placeholder="筛选股票、交易日或排名" label="模型预测分页"><el-table :data="predictionRows" max-height="420"><el-table-column prop="session" label="交易日" min-width="118"/><el-table-column prop="rank" label="排名" width="70" align="right"/><el-table-column prop="symbol" label="股票" min-width="108"/><el-table-column v-if="isRegime" prop="regime" label="市场状态" min-width="105"/><el-table-column v-if="isRegime" prop="expert_key" label="使用专家" min-width="105"/><el-table-column label="预测分" min-width="115" align="right"><template #default="{row}">{{ metric(row.score,6) }}</template></el-table-column></el-table></ListFilterPagination></template></el-tab-pane>
          <el-tab-pane label="运行记录" name="runs"><div class="run-list"><article v-for="(row,index) in [{name:'可信训练',run:training,hint:'尚未开始'},{name:'样本外预测与信号',run:prediction,hint:'等待训练完成'},{name:'可复现回测',run:backtest,hint:'等待冻结信号'}]" :key="row.name"><b>{{ index+1 }}</b><div><strong>{{ row.name }}</strong><small>{{ row.run?statusLabel(row.run.status):row.hint }}</small></div><el-tag size="small" :type="row.run?.status==='completed'?'success':'info'">{{ row.run?statusLabel(row.run.status):'待执行' }}</el-tag></article></div></el-tab-pane>
          <el-tab-pane label="技术信息" name="technical"><el-alert title="可信机器学习闭环" description="能力、策略、走步验证、模型或专家包、预测、信号和回测均可审计；浏览器看不到模型文件、原始特征行或 Worker 请求。" type="info" show-icon :closable="false"/><el-descriptions :column="1" border class="technical"><el-descriptions-item label="研究定义">{{ shortReference(selected.artifact_id) }}</el-descriptions-item><el-descriptions-item label="注册表">{{ capabilities?.registry.schema_version }}</el-descriptions-item><el-descriptions-item label="训练任务">{{ shortReference(training?.training_run_id) }}</el-descriptions-item><el-descriptions-item :label="isRegime?'模型包':'模型制品'">{{ shortReference(model?.artifact_id) }}</el-descriptions-item><el-descriptions-item label="预测任务">{{ shortReference(prediction?.prediction_run_id) }}</el-descriptions-item><el-descriptions-item label="信号快照">{{ shortReference(signal?.artifact_id) }}</el-descriptions-item></el-descriptions></el-tab-pane>
        </el-tabs>
      </el-card>
      <el-card v-else shadow="never"><el-empty description="选择一项模型研究后才加载详情"><el-button type="primary" @click="showCreate=true">新建模型研究</el-button></el-empty></el-card>
    </template>
  </ManagementWorkspace>

  <el-dialog v-model="showCreate" title="新建模型研究" width="min(820px, calc(100vw - 28px))" destroy-on-close>
    <div class="create-intro"><strong>能力来自已验证注册表</strong><p>兼容方案保持既有 LightGBM 路径；走步方案支持独立学习器；市场状态方案按沪深300状态使用不同专家。</p></div>
    <el-form label-position="top">
      <el-form-item label="研究方案"><el-radio-group v-model="form.mode" aria-label="研究方案"><el-radio-button value="compatible">兼容单模型</el-radio-button><el-radio-button value="walk_forward">净化走步模型</el-radio-button><el-radio-button value="regime" :disabled="!regimes.length||!routers.length">市场状态专家</el-radio-button></el-radio-group></el-form-item>
      <div class="form-grid"><el-form-item label="研究名称"><el-input v-model="form.name" aria-label="研究名称"/></el-form-item><el-form-item label="研究任务"><el-select v-model="form.task_id" aria-label="研究任务" clearable placeholder="留空将自动创建"><el-option v-for="task in options.tasks" :key="task.task_id" :label="task.title" :value="task.task_id"/></el-select></el-form-item></div>
      <el-form-item v-if="form.mode==='compatible'" label="兼容能力"><el-select v-model="form.capability_id" aria-label="兼容能力"><el-option v-for="item in legacyCapabilities" :key="item.capability_id" :label="item.name" :value="item.capability_id"/></el-select></el-form-item>
      <template v-else>
        <div class="form-grid three"><el-form-item label="特征集"><el-select v-model="form.feature_set"><el-option v-for="item in featureSets" :key="item.id" :label="componentLabel(item)" :value="item.id"/></el-select></el-form-item><el-form-item label="验证方案"><el-select v-model="form.validation_plan"><el-option v-for="item in validations" :key="item.id" :label="componentLabel(item)" :value="item.id" :disabled="!item.id.includes('walk-forward')"/></el-select></el-form-item><el-form-item v-if="form.mode==='walk_forward'" label="学习器"><el-select v-model="form.learner" data-testid="ml-learner"><el-option v-for="item in learners" :key="item.id" :label="componentLabel(item)" :value="item.id"/></el-select></el-form-item></div>
        <div class="validation-grid"><el-form-item label="训练交易日"><el-input-number v-model="form.train_sessions" :min="60" :max="1500"/></el-form-item><el-form-item label="验证交易日"><el-input-number v-model="form.validation_sessions" :min="10" :max="250"/></el-form-item><el-form-item label="步长"><el-input-number v-model="form.step_sessions" :min="10" :max="250"/></el-form-item><el-form-item label="折数"><el-input-number v-model="form.folds" :min="2" :max="12"/></el-form-item></div>
      </template>
      <section v-if="form.mode==='regime'" class="expert-config"><div><strong>沪深300状态专家</strong><span>未知状态自动使用“中性”后备专家</span></div><div class="expert-grid"><el-form-item v-for="expert in experts" :key="expert.key" :label="expert.label"><el-select v-model="expert.learner" :data-testid="`ml-expert-${expert.key}`"><el-option v-for="item in learners" :key="item.id" :label="componentLabel(item)" :value="item.id"/></el-select></el-form-item></div></section>
      <div class="form-grid three"><el-form-item label="预测未来交易日"><el-input-number v-model="form.horizon" :min="1" :max="20"/></el-form-item><el-form-item label="每次选择前 N 名"><el-input-number v-model="form.top_n" :min="1" :max="100"/></el-form-item><el-form-item label="调仓频率"><el-select v-model="form.rebalance" aria-label="调仓频率"><el-option label="每日" value="daily"/><el-option label="每周" value="weekly"/><el-option label="每月" value="monthly"/></el-select></el-form-item></div>
      <section class="dates"><div><strong>数据时间窗</strong><span>{{ form.mode==='compatible'?'三个区间严格前后排列':'预测区间位于开发与模型选择之后' }}</span></div><template v-if="form.mode==='compatible'"><div v-for="row in [{label:'训练',start:'train_start',end:'train_end'},{label:'验证',start:'validation_start',end:'validation_end'},{label:'预测',start:'prediction_start',end:'prediction_end'}]" :key="row.label" class="date-row"><label>{{ row.label }}</label><el-date-picker v-model="form[row.start as keyof typeof form]" value-format="YYYY-MM-DD" placeholder="开始日期"/><span>至</span><el-date-picker v-model="form[row.end as keyof typeof form]" value-format="YYYY-MM-DD" placeholder="结束日期"/></div></template><template v-else><div class="date-row"><label>开发</label><el-date-picker v-model="form.development_start" value-format="YYYY-MM-DD"/><span>至</span><el-date-picker v-model="form.development_end" value-format="YYYY-MM-DD"/></div><div class="date-row"><label>预测</label><el-date-picker v-model="form.prediction_start" value-format="YYYY-MM-DD"/><span>至</span><el-date-picker v-model="form.prediction_end" value-format="YYYY-MM-DD"/></div></template></section>
    </el-form>
    <template #footer><el-button @click="showCreate=false">取消</el-button><el-button type="primary" :loading="busy" data-testid="ml-save" @click="saveStrategy">冻结研究定义</el-button></template>
  </el-dialog>
</section>
</template>

<style scoped>
.ml-workbench{min-width:0}.research-list{display:grid;gap:9px;margin-top:4px}.research-list-item{background:transparent;border:1px solid var(--byq-border-subtle);border-radius:9px;color:var(--byq-text);cursor:pointer;display:grid;gap:7px;padding:12px;text-align:left;width:100%}.research-list-item:hover{background:var(--byq-surface-subtle)}.research-list-item.active{background:var(--byq-brand-soft);border-color:color-mix(in srgb,var(--byq-brand) 42%,var(--byq-border))}.list-head,.list-meta,.detail-heading,.result-intro{align-items:center;display:flex;gap:8px;justify-content:space-between;min-width:0}.list-head strong,.list-meta span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.method,.list-meta,.detail-heading p,.content-section p,.result-intro span,.run-list small,.expert-grid small{color:var(--byq-text-muted);font-size:11px}.detail-heading{align-items:flex-start}.detail-actions{align-items:flex-end;display:flex;flex-direction:column;gap:8px}.detail-heading>div>span{color:var(--byq-brand);font-size:10px;font-weight:800;letter-spacing:.08em}.detail-heading h3{font-size:19px;margin:3px 0}.detail-heading p,.content-section p{margin:0}.pipeline{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));list-style:none;margin:0 0 16px;padding:0}.pipeline li{align-items:flex-start;display:flex;gap:8px;min-width:0;position:relative}.pipeline li:not(:last-child):after{background:var(--byq-border);content:"";height:1px;left:30px;position:absolute;right:4px;top:13px}.pipeline b,.run-list>article>b{align-items:center;background:var(--byq-surface);border:1px solid var(--byq-border);border-radius:50%;color:var(--byq-text-muted);display:flex;flex:0 0 25px;font-size:11px;height:25px;justify-content:center;position:relative;z-index:1}.pipeline li>span{display:grid;gap:2px;position:relative;z-index:1}.pipeline strong{font-size:12px}.pipeline small{color:var(--byq-text-soft);font-size:10px}.pipeline .is-completed b{background:var(--byq-brand);border-color:var(--byq-brand);color:var(--byq-on-brand)}.pipeline .is-active b{border-color:var(--byq-brand);color:var(--byq-brand);box-shadow:0 0 0 3px var(--byq-brand-soft)}.pipeline .is-failed b{background:var(--byq-danger-soft);color:var(--byq-danger)}.next-step{align-items:center;background:var(--byq-brand-soft);border:1px solid color-mix(in srgb,var(--byq-brand) 24%,var(--byq-border));border-radius:10px;display:flex;gap:16px;justify-content:space-between;padding:14px 16px}.next-step>div:first-child{display:grid;gap:3px}.next-step>div:first-child>span{color:var(--byq-brand);font-size:10px;font-weight:800}.next-step p{color:var(--byq-text-muted);font-size:11px;margin:0}.next-actions{align-items:center;display:flex;gap:8px}.next-actions .el-select{min-width:190px}.research-tabs{margin-top:12px}.summary-grid,.metrics{display:grid;gap:9px;grid-template-columns:repeat(4,minmax(0,1fr))}.summary-grid>div{background:var(--byq-surface-subtle);border:1px solid var(--byq-border-subtle);border-radius:9px;display:grid;gap:5px;padding:12px}.summary-grid span,.metrics span{color:var(--byq-text-muted);font-size:11px}.summary-grid strong{font-size:13px}.summary-grid small{color:var(--byq-text-soft);font-size:10px}.content-section{border-top:1px solid var(--byq-border-subtle);margin-top:18px;padding-top:16px}.content-section h4{font-size:14px;margin:0}.periods{display:grid;gap:8px;grid-template-columns:repeat(3,minmax(0,1fr));margin:12px 0 0}.periods.two{grid-template-columns:repeat(2,minmax(0,1fr))}.periods>div{border-left:2px solid var(--byq-border);display:grid;gap:4px;padding:4px 10px}.periods dt{color:var(--byq-text-muted);font-size:11px}.periods dd{font-size:12px;margin:0}.metrics{margin-top:12px}.metrics>div{display:grid;gap:4px}.metrics strong{font-size:17px}.result-intro{margin-bottom:10px}.result-intro>div{display:grid;gap:3px}.run-list{display:grid;gap:8px}.run-list article{align-items:center;border:1px solid var(--byq-border-subtle);border-radius:9px;display:grid;gap:10px;grid-template-columns:auto minmax(0,1fr) auto;padding:12px}.run-list article>div{display:grid;gap:3px}.technical{margin-top:12px}.technical :deep(.el-descriptions__content){overflow-wrap:anywhere}.create-intro{background:var(--byq-surface-subtle);border-radius:9px;margin-bottom:16px;padding:12px 14px}.create-intro p{color:var(--byq-text-muted);font-size:12px;margin:4px 0}.form-grid,.validation-grid,.expert-grid{display:grid;gap:12px;grid-template-columns:repeat(2,minmax(0,1fr))}.form-grid.three,.validation-grid,.expert-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.form-grid :deep(.el-input-number),.form-grid :deep(.el-select),.validation-grid :deep(.el-input-number),.expert-grid :deep(.el-select){width:100%}.dates,.expert-config{border-top:1px solid var(--byq-border-subtle);display:grid;gap:10px;padding-top:14px}.dates>div:first-child,.expert-config>div:first-child{display:flex;justify-content:space-between}.dates>div:first-child span,.expert-config>div:first-child span{color:var(--byq-text-muted);font-size:11px}.date-row{align-items:center;display:grid;gap:9px;grid-template-columns:44px minmax(0,1fr) auto minmax(0,1fr)}.date-row label{color:var(--byq-text-muted);font-size:12px;font-weight:700}.date-row :deep(.el-date-editor){width:100%}.expert-grid article{border:1px solid var(--byq-border-subtle);border-radius:9px;display:grid;gap:5px;padding:11px}.expert-grid article span{font-size:12px}.regime-counts{align-items:center;display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}.regime-counts>span{color:var(--byq-text-muted);font-size:11px;margin-right:auto}@media(max-width:1120px){.summary-grid,.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.pipeline small{display:none}}@media(max-width:760px){.next-step,.next-actions{align-items:stretch;flex-direction:column}.next-actions .el-select,.next-actions .el-button{width:100%}.pipeline{gap:4px}.pipeline li{align-items:center;display:grid;gap:5px;justify-items:center;text-align:center}.pipeline li:not(:last-child):after{left:calc(50% + 13px);right:calc(-50% + 13px)}.periods,.periods.two,.form-grid,.form-grid.three,.validation-grid,.expert-grid{grid-template-columns:1fr}.date-row{grid-template-columns:1fr}.date-row>span{display:none}.dates>div:first-child,.expert-config>div:first-child{align-items:flex-start;flex-direction:column}}@media(max-width:480px){.summary-grid,.metrics{grid-template-columns:1fr}.list-meta time{display:none}}
</style>
