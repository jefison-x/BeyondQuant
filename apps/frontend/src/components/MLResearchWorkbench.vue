<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { approveMLStrategy, createMLPrediction, createMLStrategy, createMLTraining, getMLPrediction, getMLTraining, getMLWorkspace, type MLArtifact, type MLRun, type MLWorkspace } from "@/api/mlResearch";
import { createTask } from "@/api/research";
import { getBacktest, runBacktest, submitBacktest } from "@/api/quant";

const loading = ref(true), busy = ref(false), error = ref("");
const workspace = ref<MLWorkspace>({ tasks: [], pools: [], artifacts: [], training_runs: [], prediction_runs: [], backtests: [] });
const form = reactive({ task_id: "", pool_id: "", name: "LightGBM 收益排序", train_start: "2026-01-01", train_end: "2026-02-19", validation_start: "2026-02-20", validation_end: "2026-03-11", prediction_start: "2026-03-12", prediction_end: "2026-03-30", horizon: 5, top_n: 1, rebalance: "weekly", capital: 1000000, lot_size: 100 });
const selectedStrategy = ref(""), selectedApproval = ref(""), training = ref<MLRun | null>(null), prediction = ref<MLRun | null>(null), backtest = ref<Record<string, any> | null>(null);
let timer: number | undefined;
const activePools = computed(() => workspace.value.pools.filter(p => p.status === "active" && p.current_snapshot_id));
const artifacts = (kind: string) => workspace.value.artifacts.filter(a => a.kind === kind);
const artifact = (id?: string) => workspace.value.artifacts.find(a => a.artifact_id === id);
const predictionRows = computed(() => (artifact(prediction.value?.prediction_artifact_id)?.content.rows ?? []) as Array<Record<string, any>>);
const model = computed(() => artifact(training.value?.model_artifact_id));
const signal = computed(() => artifact(prediction.value?.signal_artifact_id));

async function load() {
  loading.value = true; error.value = "";
  try {
    workspace.value = await getMLWorkspace();
    form.task_id ||= String(workspace.value.tasks[0]?.task_id ?? "");
    form.pool_id ||= String(activePools.value[0]?.pool_id ?? "");
    selectedStrategy.value ||= artifacts("ml_strategy_version")[0]?.artifact_id ?? "";
    selectedApproval.value ||= artifacts("ml_strategy_approval").find(item => item.content.decision === "approved" && (!selectedStrategy.value || item.content.ml_strategy_artifact_id === selectedStrategy.value))?.artifact_id ?? "";
    training.value ||= workspace.value.training_runs[0] ?? null;
    prediction.value ||= workspace.value.prediction_runs[0] ?? null;
    backtest.value ||= workspace.value.backtests.find(item => !selectedStrategy.value || item.strategy_version_artifact_id === selectedStrategy.value) ?? null;
  } catch (e) { error.value = e instanceof Error ? e.message : "加载失败"; }
  finally { loading.value = false; }
}
onMounted(load); onBeforeUnmount(() => timer && clearTimeout(timer));
const chosenPool = computed(() => activePools.value.find(p => p.pool_id === form.pool_id));
async function ensureTask() { if (form.task_id) return; const body: any = await createTask("LightGBM 产品闭环", "验证训练、模型制品、样本外预测、冻结信号与回测"); form.task_id = body.task_id ?? body.task?.task_id; }
async function saveStrategy() {
  busy.value = true;
  try { await ensureTask(); const body = await createMLStrategy({ task_id: form.task_id, strategy: { schema_version: "ml-strategy-version.v1", name: form.name, learner: { kind: "lightgbm_regression", profile: "byq-lightgbm-cpu-v1" }, feature_set: { id: "price-volume-basic-v1" }, target: { kind: "forward_return", horizon_sessions: form.horizon }, split: { train: { start: form.train_start, end: form.train_end }, validation: { start: form.validation_start, end: form.validation_end }, prediction: { start: form.prediction_start, end: form.prediction_end } }, learner_parameters: {}, signal_policy: { kind: "top_n_equal_weight", top_n: form.top_n, rebalance: form.rebalance } } }); selectedStrategy.value = body.artifact.artifact_id; ElMessage.success("策略版本已冻结"); await load(); }
  catch (e) { ElMessage.error(e instanceof Error ? e.message : "保存失败"); } finally { busy.value = false; }
}
async function approveAndTrain() {
  if (!selectedStrategy.value || !chosenPool.value) return;
  await ElMessageBox.confirm("批准后将使用当前冻结股票池启动真实 LightGBM 训练。", "人工批准", { type: "warning", confirmButtonText: "批准并训练" }); busy.value = true;
  try { const approved = await approveMLStrategy({ task_id: form.task_id, ml_strategy_artifact_id: selectedStrategy.value, decision: "approved", rationale: "Phase 74 产品界面人工批准" }); selectedApproval.value = approved.artifact.artifact_id; const body = await createMLTraining({ task_id: form.task_id, ml_strategy_artifact_id: selectedStrategy.value, stock_pool_snapshot_id: chosenPool.value.current_snapshot_id }); training.value = body.training_run; ElMessage.success("训练已提交"); pollTraining(); } catch (e) { ElMessage.error(e instanceof Error ? e.message : "训练提交失败"); } finally { busy.value = false; }
}
function pollTraining() { if (!training.value?.training_run_id || ["completed","failed","cancelled"].includes(training.value.status)) { load(); return; } timer = window.setTimeout(async () => { training.value = (await getMLTraining(training.value!.training_run_id!)).training_run; pollTraining(); }, 1200); }
async function predict() { if (!training.value?.model_artifact_id || !selectedApproval.value) return; busy.value = true; try { prediction.value = (await createMLPrediction({ task_id: form.task_id, model_artifact_id: training.value.model_artifact_id, approval_artifact_id: selectedApproval.value, execution: { initial_capital: form.capital, lot_size: form.lot_size } })).prediction_run; ElMessage.success("样本外预测已提交"); pollPrediction(); } catch (e) { ElMessage.error(e instanceof Error ? e.message : "预测失败"); } finally { busy.value = false; } }
function pollPrediction() { if (!prediction.value?.prediction_run_id || ["completed","failed","cancelled"].includes(prediction.value.status)) { load(); return; } timer = window.setTimeout(async () => { prediction.value = (await getMLPrediction(prediction.value!.prediction_run_id!)).prediction_run; pollPrediction(); }, 1200); }
async function backtestSignal() { if (!prediction.value?.signal_artifact_id || !selectedStrategy.value || !selectedApproval.value) return; busy.value = true; try { const made: any = await submitBacktest({ task_id: form.task_id, strategy_version_artifact_id: selectedStrategy.value, approval_artifact_id: selectedApproval.value, signal_snapshot_artifact_id: prediction.value.signal_artifact_id, trace_id: `ml-ui-${Date.now()}`, idempotency_key: `ml-ui-${Date.now()}` }, ""); const id = made.job.job_id; backtest.value = await runBacktest(id, ""); const watch = async () => { const job: any = await getBacktest(id, ""); backtest.value = job; if (!["completed","failed","cancelled"].includes(job.status)) timer = window.setTimeout(watch, 1200); }; watch(); } catch (e) { ElMessage.error(e instanceof Error ? e.message : "回测失败"); } finally { busy.value = false; } }
</script>

<template><section class="ml-workbench">
  <el-alert title="可靠 LightGBM 最小闭环" description="策略、批准、训练、模型、样本外预测和冻结信号均持久化；浏览器看不到模型文件和原始特征样本。" type="info" show-icon :closable="false" />
  <div v-if="loading" class="base-loading">加载中...</div><div v-else-if="error" class="base-error" role="alert">{{ error }} <el-button link @click="load">重试</el-button></div>
  <template v-else><el-card shadow="never"><template #header><strong>1. 冻结研究定义</strong></template><el-form label-position="top"><div class="grid"><el-form-item label="研究任务"><el-select v-model="form.task_id" aria-label="研究任务" clearable placeholder="留空将自动创建"><el-option v-for="t in workspace.tasks" :key="t.task_id" :label="t.title" :value="t.task_id" /></el-select></el-form-item><el-form-item label="冻结股票池"><el-select v-model="form.pool_id" aria-label="冻结股票池" data-testid="ml-pool"><el-option v-for="p in activePools" :key="p.pool_id" :label="`${p.name} · ${p.version} · ${p.member_count}只`" :value="p.pool_id" /></el-select></el-form-item><el-form-item label="策略名称"><el-input v-model="form.name" /></el-form-item><el-form-item label="调仓"><el-select v-model="form.rebalance" aria-label="调仓频率"><el-option label="每周" value="weekly"/><el-option label="每日" value="daily"/><el-option label="每月" value="monthly"/></el-select></el-form-item></div><div class="dates"><el-date-picker v-model="form.train_start" value-format="YYYY-MM-DD" placeholder="训练开始"/><el-date-picker v-model="form.train_end" value-format="YYYY-MM-DD" placeholder="训练结束"/><el-date-picker v-model="form.validation_start" value-format="YYYY-MM-DD" placeholder="验证开始"/><el-date-picker v-model="form.validation_end" value-format="YYYY-MM-DD" placeholder="验证结束"/><el-date-picker v-model="form.prediction_start" value-format="YYYY-MM-DD" placeholder="预测开始"/><el-date-picker v-model="form.prediction_end" value-format="YYYY-MM-DD" placeholder="预测结束"/></div><el-button type="primary" :loading="busy" data-testid="ml-save" @click="saveStrategy">冻结策略版本</el-button></el-form></el-card>
  <el-card shadow="never"><template #header><strong>2. 人工批准与训练</strong></template><p class="muted">策略：{{ selectedStrategy || "尚未冻结" }}　训练：{{ training?.status || "未提交" }}</p><el-button type="primary" :disabled="!selectedStrategy || !chosenPool" :loading="busy" data-testid="ml-train" @click="approveAndTrain">批准并开始训练</el-button><el-descriptions v-if="model" :column="1" border><el-descriptions-item label="模型制品">{{ model.artifact_id }}</el-descriptions-item><el-descriptions-item label="最佳轮次">{{ model.content.best_iteration }}</el-descriptions-item><el-descriptions-item label="指标">{{ JSON.stringify(model.content.metrics) }}</el-descriptions-item><el-descriptions-item label="运行时">{{ model.content.runtime_identity }}</el-descriptions-item></el-descriptions></el-card>
  <el-card shadow="never"><template #header><strong>3. 样本外预测与冻结信号</strong></template><p class="muted">预测：{{ prediction?.status || "未提交" }}　信号：{{ signal?.artifact_id || "尚未生成" }}</p><el-button type="primary" :disabled="training?.status !== 'completed' || !selectedApproval" :loading="busy" data-testid="ml-predict" @click="predict">生成预测与冻结信号</el-button><el-table v-if="predictionRows.length" :data="predictionRows" max-height="300"><el-table-column prop="session" label="交易日"/><el-table-column prop="rank" label="排名"/><el-table-column prop="symbol" label="股票"/><el-table-column prop="score" label="预测分"/></el-table></el-card>
  <el-card shadow="never"><template #header><strong>4. 可复现回测</strong></template><el-button type="success" :disabled="prediction?.status !== 'completed'" :loading="busy" data-testid="ml-backtest" @click="backtestSignal">提交并运行回测</el-button><el-tag v-if="backtest" :type="backtest.status === 'completed' ? 'success' : 'info'">{{ backtest.status }}</el-tag></el-card></template>
</section></template>
<style scoped>.ml-workbench{display:grid;gap:1rem;min-width:0}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1rem}.dates{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.75rem;margin-bottom:1rem}.dates>*{width:100%}.muted{color:var(--byq-text-muted);font-size:12px;overflow-wrap:anywhere}.ml-workbench :deep(.el-descriptions__content){overflow-wrap:anywhere;word-break:break-word}@media(max-width:800px){.grid,.dates{grid-template-columns:1fr}}</style>
