<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { approveMLStrategy, createMLPrediction, createMLStrategy, createMLTraining, getMLPrediction, getMLTraining, getMLWorkspace, type MLRun, type MLWorkspace } from "@/api/mlResearch";
import { createTask } from "@/api/research";
import { getBacktest, runBacktest, submitBacktest } from "@/api/quant";
import ManagementWorkspace from "@/components/layout/ManagementWorkspace.vue";
import { formatChinaTime } from "@/time";
import { shortReference, statusLabel } from "@/display";

const CAPABILITIES = [{ id: "lightgbm-return-ranking", name: "LightGBM 收益排序", summary: "基于价格与成交量特征预测未来收益，并按得分生成组合信号。", learner: "lightgbm_regression", profile: "byq-lightgbm-cpu-v1", features: "price-volume-basic-v1" }];
const router = useRouter();
const loading = ref(true), busy = ref(false), error = ref(""), showCreate = ref(false);
const search = ref(""), statusFilter = ref("all"), activeTab = ref("overview");
const workspace = ref<MLWorkspace>({ tasks: [], pools: [], artifacts: [], training_runs: [], prediction_runs: [], backtests: [] });
const form = reactive({ capability_id: CAPABILITIES[0].id, task_id: "", pool_id: "", name: "LightGBM 收益排序", train_start: "2026-01-01", train_end: "2026-02-19", validation_start: "2026-02-20", validation_end: "2026-03-11", prediction_start: "2026-03-12", prediction_end: "2026-03-30", horizon: 5, top_n: 1, rebalance: "weekly", capital: 1000000, lot_size: 100 });
const selectedStrategy = ref(""), selectedApproval = ref("");
const training = ref<MLRun | null>(null), prediction = ref<MLRun | null>(null), backtest = ref<Record<string, any> | null>(null);
let timer: number | undefined;

const activePools = computed(() => workspace.value.pools.filter(p => p.status === "active" && p.current_snapshot_id));
const strategies = computed(() => workspace.value.artifacts.filter(a => a.kind === "ml_strategy_version"));
const selected = computed(() => strategies.value.find(a => a.artifact_id === selectedStrategy.value) ?? null);
const content = computed(() => selected.value?.content ?? {});
const artifacts = (kind: string) => workspace.value.artifacts.filter(a => a.kind === kind);
const artifact = (id?: string) => workspace.value.artifacts.find(a => a.artifact_id === id);
const model = computed(() => artifact(training.value?.model_artifact_id));
const signal = computed(() => artifact(prediction.value?.signal_artifact_id));
const predictionRows = computed(() => (artifact(prediction.value?.prediction_artifact_id)?.content.rows ?? []) as Record<string, any>[]);
const capability = computed(() => CAPABILITIES.find(c => c.id === form.capability_id) ?? CAPABILITIES[0]);
const taskId = computed(() => selected.value?.task_id || form.task_id);
const chosenPool = computed(() => activePools.value.find(p => p.pool_id === form.pool_id));
const selectedPool = computed(() => workspace.value.pools.find(p => p.current_snapshot_id === (training.value?.stock_pool_snapshot_id || prediction.value?.stock_pool_snapshot_id)) ?? chosenPool.value ?? null);

function related(strategyId: string) {
  return {
    train: workspace.value.training_runs.find(r => r.ml_strategy_artifact_id === strategyId) ?? null,
    predict: workspace.value.prediction_runs.find(r => r.ml_strategy_artifact_id === strategyId) ?? null,
    backtest: workspace.value.backtests.find(r => r.strategy_version_artifact_id === strategyId) ?? null,
  };
}
function selectStrategy(id: string) {
  selectedStrategy.value = id;
  selectedApproval.value = artifacts("ml_strategy_approval").find(a => a.content.decision === "approved" && a.content.ml_strategy_artifact_id === id)?.artifact_id ?? "";
  const runs = related(id); training.value = runs.train; prediction.value = runs.predict; backtest.value = runs.backtest;
  activeTab.value = "overview";
}
async function load() {
  loading.value = true; error.value = "";
  try {
    workspace.value = await getMLWorkspace();
    form.task_id ||= String(workspace.value.tasks[0]?.task_id ?? "");
    form.pool_id ||= String(activePools.value[0]?.pool_id ?? "");
    const id = strategies.value.some(a => a.artifact_id === selectedStrategy.value) ? selectedStrategy.value : strategies.value[0]?.artifact_id ?? "";
    if (id) selectStrategy(id); else { selectedStrategy.value = ""; training.value = prediction.value = null; backtest.value = null; }
  } catch (e) { error.value = e instanceof Error ? e.message : "加载失败"; }
  finally { loading.value = false; }
}
onMounted(load); onBeforeUnmount(() => timer && clearTimeout(timer));

function stage(id: string) {
  const r = related(id);
  if (r.backtest?.status === "completed") return "completed";
  if (r.backtest) return "backtest";
  if (r.predict?.status === "completed") return "signal";
  if (r.predict) return "prediction";
  if (r.train?.status === "completed") return "model";
  if (r.train) return "training";
  return "definition";
}
const STAGES: Record<string, string> = { definition: "待训练", training: "训练中", model: "模型已就绪", prediction: "预测中", signal: "信号已就绪", backtest: "回测中", completed: "已完成" };
const filtered = computed(() => strategies.value.filter(a => {
  const task = workspace.value.tasks.find(t => t.task_id === a.task_id);
  const text = `${a.content.name ?? ""} ${task?.title ?? ""} ${a.artifact_id}`.toLowerCase();
  const s = stage(a.artifact_id);
  return (!search.value || text.includes(search.value.toLowerCase())) && (statusFilter.value === "all" || (statusFilter.value === "active" && s !== "completed") || (statusFilter.value === "completed" && s === "completed"));
}));
function stepState(run: Record<string, any> | MLRun | null) { return !run ? "pending" : run.status === "completed" ? "completed" : ["failed", "cancelled"].includes(run.status) ? "failed" : "active"; }
const steps = computed(() => [
  { label: "研究定义", hint: "范围与方法已冻结", state: selected.value ? "completed" : "pending" },
  { label: "训练验证", hint: "训练集与验证集隔离", state: stepState(training.value) },
  { label: "预测与信号", hint: "只使用样本外数据", state: stepState(prediction.value) },
  { label: "回测复核", hint: "复用冻结信号", state: stepState(backtest.value) },
]);
const next = computed(() => {
  if (!selected.value) return { title: "创建第一项模型研究", hint: "先选择研究目标和已验证的方法。", action: "create", label: "新建模型研究" };
  if (!training.value || ["failed", "cancelled"].includes(training.value.status)) return { title: "批准研究并开始训练", hint: "确认冻结股票池后，在可信计算环境中训练。", action: "train", label: training.value ? "重新开始训练" : "批准并开始训练" };
  if (training.value.status !== "completed") return { title: "模型正在训练", hint: "完成后即可生成样本外预测，无需重复提交。", action: "wait", label: "训练进行中" };
  if (!prediction.value || ["failed", "cancelled"].includes(prediction.value.status)) return { title: "生成样本外预测", hint: "使用已验证模型生成排名和冻结信号。", action: "predict", label: prediction.value ? "重新生成预测" : "生成预测与信号" };
  if (prediction.value.status !== "completed") return { title: "正在生成预测与信号", hint: "系统正在完成排名与信号冻结。", action: "wait", label: "预测进行中" };
  if (!backtest.value || ["failed", "cancelled"].includes(String(backtest.value.status))) return { title: "用回测复核研究结论", hint: "回测不会重新训练或改变排名。", action: "backtest", label: "提交并运行回测" };
  if (backtest.value.status !== "completed") return { title: "回测正在运行", hint: "完成后可查看完整收益与成交证据。", action: "wait", label: "回测进行中" };
  return { title: "研究闭环已完成", hint: "模型、预测、信号和回测结果均已留存。", action: "view", label: "查看完整回测" };
});

async function ensureTask() { if (!form.task_id) { const body: any = await createTask("模型收益排序研究", "验证训练、样本外预测、冻结信号与回测"); form.task_id = body.task_id ?? body.task?.task_id; } }
async function saveStrategy() {
  busy.value = true;
  try {
    await ensureTask(); const c = capability.value;
    const body = await createMLStrategy({ task_id: form.task_id, strategy: { schema_version: "ml-strategy-version.v1", name: form.name, learner: { kind: c.learner, profile: c.profile }, feature_set: { id: c.features }, target: { kind: "forward_return", horizon_sessions: form.horizon }, split: { train: { start: form.train_start, end: form.train_end }, validation: { start: form.validation_start, end: form.validation_end }, prediction: { start: form.prediction_start, end: form.prediction_end } }, learner_parameters: {}, signal_policy: { kind: "top_n_equal_weight", top_n: form.top_n, rebalance: form.rebalance } } });
    selectedStrategy.value = body.artifact.artifact_id; showCreate.value = false; ElMessage.success("研究定义已冻结，可以进入训练"); await load();
  } catch (e) { ElMessage.error(e instanceof Error ? e.message : "保存失败"); } finally { busy.value = false; }
}
async function approveAndTrain() {
  if (!selected.value || !chosenPool.value) return;
  await ElMessageBox.confirm(`将使用“${chosenPool.value.name}”的当前冻结快照开始训练。`, "确认训练范围", { type: "warning", confirmButtonText: "批准并开始训练", cancelButtonText: "返回检查" });
  busy.value = true;
  try {
    const approved = await approveMLStrategy({ task_id: taskId.value, ml_strategy_artifact_id: selected.value.artifact_id, decision: "approved", rationale: "用户在模型研究工作台确认范围并批准训练" });
    selectedApproval.value = approved.artifact.artifact_id;
    training.value = (await createMLTraining({ task_id: taskId.value, ml_strategy_artifact_id: selected.value.artifact_id, stock_pool_snapshot_id: chosenPool.value.current_snapshot_id })).training_run;
    ElMessage.success("训练已提交，可稍后回来查看"); pollTraining();
  } catch (e) { ElMessage.error(e instanceof Error ? e.message : "训练提交失败"); } finally { busy.value = false; }
}
function pollTraining() { if (!training.value?.training_run_id || ["completed", "failed", "cancelled"].includes(training.value.status)) { void load(); return; } timer = window.setTimeout(async () => { try { training.value = (await getMLTraining(training.value!.training_run_id!)).training_run; pollTraining(); } catch { void load(); } }, 1200); }
async function predict() {
  if (!training.value?.model_artifact_id || !selectedApproval.value) return; busy.value = true;
  try { prediction.value = (await createMLPrediction({ task_id: taskId.value, model_artifact_id: training.value.model_artifact_id, approval_artifact_id: selectedApproval.value, execution: { initial_capital: form.capital, lot_size: form.lot_size } })).prediction_run; ElMessage.success("样本外预测已提交"); pollPrediction(); }
  catch (e) { ElMessage.error(e instanceof Error ? e.message : "预测失败"); } finally { busy.value = false; }
}
function pollPrediction() { if (!prediction.value?.prediction_run_id || ["completed", "failed", "cancelled"].includes(prediction.value.status)) { void load(); return; } timer = window.setTimeout(async () => { try { prediction.value = (await getMLPrediction(prediction.value!.prediction_run_id!)).prediction_run; pollPrediction(); } catch { void load(); } }, 1200); }
async function backtestSignal() {
  if (!prediction.value?.signal_artifact_id || !selected.value || !selectedApproval.value) return; busy.value = true;
  try { const rid = `ml-ui-${Date.now()}`; const made: any = await submitBacktest({ task_id: taskId.value, strategy_version_artifact_id: selected.value.artifact_id, approval_artifact_id: selectedApproval.value, signal_snapshot_artifact_id: prediction.value.signal_artifact_id, trace_id: rid, idempotency_key: rid }, ""); const id = made.job.job_id; backtest.value = await runBacktest(id, ""); ElMessage.success("回测已提交"); const watch = async () => { const job: any = await getBacktest(id, ""); backtest.value = job; if (!["completed", "failed", "cancelled"].includes(job.status)) timer = window.setTimeout(watch, 1200); else await load(); }; void watch(); }
  catch (e) { ElMessage.error(e instanceof Error ? e.message : "回测失败"); } finally { busy.value = false; }
}
function runNext() { if (next.value.action === "create") showCreate.value = true; else if (next.value.action === "train") void approveAndTrain(); else if (next.value.action === "predict") void predict(); else if (next.value.action === "backtest") void backtestSignal(); else if (next.value.action === "view" && backtest.value?.job_id) void router.push({ path: "/backtest", query: { job: String(backtest.value.job_id) } }); }
const metric = (value: unknown, digits = 4) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "-";
const period = (value: any) => value?.start && value?.end ? `${value.start} 至 ${value.end}` : "-";
const rebalance = (value: unknown) => ({ daily: "每日", weekly: "每周", monthly: "每月" } as Record<string, string>)[String(value)] ?? "-";
const taskTitle = (id: string) => String(workspace.value.tasks.find(t => t.task_id === id)?.title ?? `研究任务 ${shortReference(id)}`);
</script>

<template>
<section class="ml-workbench">
  <div v-if="loading" class="base-loading" role="status">加载模型研究...</div>
  <div v-else-if="error && !selected" class="base-error" role="alert">{{ error }} <el-button link @click="load">重试</el-button></div>
  <ManagementWorkspace v-else eyebrow="核心研究资产" title="模型研究目录与实验进程" description="从研究定义、可信训练和样本外预测，逐步推进到冻结信号与可复现回测。" catalog-label="模型研究" :count="strategies.length" @return="router.push('/agent')">
    <template #return>返回投研对话</template>
    <template #actions><el-button @click="load">刷新</el-button><el-button type="primary" @click="showCreate = true">新建模型研究</el-button></template>
    <template #summary>当前仅展示已验证、可审计的模型能力</template>
    <template #catalog>
      <el-card shadow="never" class="research-catalog"><template #header><div class="card-heading"><span class="card-title">研究目录</span><small class="card-sub">按研究目标查找，不需要记住制品编号</small></div></template>
        <div class="catalog-toolbar"><el-input v-model="search" aria-label="搜索模型研究" placeholder="搜索研究名称或任务" clearable/><el-radio-group v-model="statusFilter" aria-label="模型研究状态" size="small"><el-radio-button value="all">全部</el-radio-button><el-radio-button value="active">进行中</el-radio-button><el-radio-button value="completed">已完成</el-radio-button></el-radio-group></div>
        <el-empty v-if="!filtered.length" description="暂无模型研究"><el-button type="primary" @click="showCreate = true">创建第一项研究</el-button></el-empty>
        <div v-else class="research-list" role="list"><button v-for="item in filtered" :key="item.artifact_id" type="button" class="research-list-item" :class="{active:item.artifact_id===selectedStrategy}" :aria-pressed="item.artifact_id===selectedStrategy" @click="selectStrategy(item.artifact_id)"><span class="list-head"><strong>{{ item.content.name || '未命名模型研究' }}</strong><el-tag size="small" :type="stage(item.artifact_id)==='completed'?'success':'info'">{{ STAGES[stage(item.artifact_id)] }}</el-tag></span><span class="method">LightGBM · 收益排序</span><span class="list-meta"><span>{{ taskTitle(item.task_id) }}</span><time>{{ formatChinaTime(item.created_at) }}</time></span></button></div>
      </el-card>
    </template>
    <template #detail>
      <el-card v-if="selected" shadow="never" class="research-detail"><template #header><div class="detail-heading"><div><span>LightGBM · 收益排序</span><h3>{{ content.name || '未命名模型研究' }}</h3><p>{{ taskTitle(selected.task_id) }}</p></div><el-tag :type="stage(selected.artifact_id)==='completed'?'success':'info'">{{ STAGES[stage(selected.artifact_id)] }}</el-tag></div></template>
        <ol class="pipeline" aria-label="模型研究进度"><li v-for="(step,index) in steps" :key="step.label" :class="`is-${step.state}`"><b>{{ step.state==='completed'?'✓':index+1 }}</b><span><strong>{{ step.label }}</strong><small>{{ step.hint }}</small></span></li></ol>
        <section class="next-step"><div><span>建议下一步</span><strong>{{ next.title }}</strong><p>{{ next.hint }}</p></div><div class="next-actions"><el-select v-if="next.action==='train'" v-model="form.pool_id" aria-label="训练使用的冻结股票池" data-testid="ml-pool" placeholder="选择冻结股票池"><el-option v-for="pool in activePools" :key="pool.pool_id" :label="`${pool.name} · ${pool.member_count}只`" :value="pool.pool_id"/></el-select><el-button type="primary" :disabled="next.action==='wait'||(next.action==='train'&&!chosenPool)" :loading="busy" :data-testid="next.action==='train'?'ml-train':next.action==='predict'?'ml-predict':next.action==='backtest'?'ml-backtest':undefined" @click="runNext">{{ next.label }}</el-button></div></section>
        <el-tabs v-model="activeTab" class="research-tabs">
          <el-tab-pane label="研究概览" name="overview"><div class="summary-grid"><div><span>研究方法</span><strong>LightGBM 收益排序</strong><small>可信 CPU 训练</small></div><div><span>研究范围</span><strong>{{ selectedPool?.name || '训练时选择股票池' }}</strong><small>{{ selectedPool?`${selectedPool.member_count} 只股票`:'使用不可变成员快照' }}</small></div><div><span>预测目标</span><strong>未来 {{ content.target?.horizon_sessions ?? form.horizon }} 个交易日收益</strong><small>时间顺序切分</small></div><div><span>组合规则</span><strong>前 {{ content.signal_policy?.top_n ?? form.top_n }} 名等权</strong><small>{{ rebalance(content.signal_policy?.rebalance ?? form.rebalance) }}调仓</small></div></div>
            <section class="content-section"><h4>数据时间窗</h4><p>训练、验证和预测按时间先后隔离，预测区间不包含标签。</p><dl class="periods"><div><dt>学习历史规律</dt><dd>{{ period(content.split?.train) }}</dd></div><div><dt>验证模型表现</dt><dd>{{ period(content.split?.validation) }}</dd></div><div><dt>生成样本外预测</dt><dd>{{ period(content.split?.prediction) }}</dd></div></dl></section>
            <section v-if="model" class="content-section"><h4>训练结果</h4><p>指标只来自验证区间，不代表未来收益承诺。</p><div class="metrics"><div><span>验证误差 RMSE</span><strong>{{ metric(model.content.metrics?.validation_rmse,6) }}</strong></div><div><span>排序相关 Rank IC</span><strong>{{ metric(model.content.metrics?.validation_rank_ic) }}</strong></div><div><span>最佳迭代轮次</span><strong>{{ model.content.best_iteration??'-' }}</strong></div><div><span>验证样本数</span><strong>{{ model.content.counts?.validation_rows??model.content.metrics?.validation_rows??'-' }}</strong></div></div></section>
          </el-tab-pane>
          <el-tab-pane label="预测结果" name="prediction"><el-empty v-if="!predictionRows.length" description="完成训练后可在这里查看样本外排名"/><template v-else><div class="result-intro"><div><strong>样本外排名</strong><span>共 {{ predictionRows.length }} 条可见记录</span></div><el-tag v-if="signal" type="success">冻结信号已生成</el-tag></div><el-table :data="predictionRows" max-height="420"><el-table-column prop="session" label="交易日" min-width="120"/><el-table-column prop="rank" label="排名" width="80" align="right"/><el-table-column prop="symbol" label="股票" min-width="120"/><el-table-column label="预测分" min-width="120" align="right"><template #default="{row}">{{ metric(row.score,6) }}</template></el-table-column></el-table></template></el-tab-pane>
          <el-tab-pane label="运行记录" name="runs"><div class="run-list"><article v-for="(row,index) in [{name:'可信训练',run:training,hint:'尚未开始'},{name:'样本外预测与信号',run:prediction,hint:'等待训练完成'},{name:'可复现回测',run:backtest,hint:'等待冻结信号'}]" :key="row.name"><b>{{ index+1 }}</b><div><strong>{{ row.name }}</strong><small>{{ row.run?statusLabel(row.run.status):row.hint }}</small></div><el-tag size="small" :type="row.run?.status==='completed'?'success':'info'">{{ row.run?statusLabel(row.run.status):'待执行' }}</el-tag></article></div></el-tab-pane>
          <el-tab-pane label="技术信息" name="technical"><el-alert title="可靠 LightGBM 最小闭环" description="策略、批准、训练、模型、样本外预测和冻结信号均持久化；浏览器看不到模型文件和原始特征样本。" type="info" show-icon :closable="false"/><el-descriptions :column="1" border class="technical"><el-descriptions-item label="研究定义">{{ shortReference(selected.artifact_id) }}</el-descriptions-item><el-descriptions-item label="训练任务">{{ shortReference(training?.training_run_id) }}</el-descriptions-item><el-descriptions-item label="模型制品">{{ shortReference(model?.artifact_id) }}</el-descriptions-item><el-descriptions-item label="预测任务">{{ shortReference(prediction?.prediction_run_id) }}</el-descriptions-item><el-descriptions-item label="信号快照">{{ shortReference(signal?.artifact_id) }}</el-descriptions-item><el-descriptions-item label="运行环境">{{ model?.content.runtime_identity??'训练完成后记录' }}</el-descriptions-item></el-descriptions></el-tab-pane>
        </el-tabs>
      </el-card>
      <el-card v-else shadow="never"><el-empty description="选择一项模型研究，或从明确的研究目标开始"><el-button type="primary" @click="showCreate=true">新建模型研究</el-button></el-empty></el-card>
    </template>
  </ManagementWorkspace>
  <el-dialog v-model="showCreate" title="新建模型研究" width="min(760px, calc(100vw - 28px))" destroy-on-close><div class="create-intro"><strong>先定义要研究什么</strong><p>选择研究方法、数据时间窗和组合规则。提交后形成不可变定义，训练会在下一步单独确认。</p></div><el-form label-position="top"><div class="form-grid"><el-form-item label="研究名称"><el-input v-model="form.name" aria-label="研究名称"/></el-form-item><el-form-item label="研究任务"><el-select v-model="form.task_id" aria-label="研究任务" clearable placeholder="留空将自动创建"><el-option v-for="task in workspace.tasks" :key="task.task_id" :label="task.title" :value="task.task_id"/></el-select></el-form-item></div><el-form-item label="研究方法"><el-select v-model="form.capability_id" aria-label="研究方法"><el-option v-for="c in CAPABILITIES" :key="c.id" :label="c.name" :value="c.id"/></el-select><p class="help">{{ capability.summary }} 当前只开放通过运行验证的能力。</p></el-form-item><div class="form-grid three"><el-form-item label="预测未来交易日"><el-input-number v-model="form.horizon" :min="1" :max="20"/></el-form-item><el-form-item label="每次选择前 N 名"><el-input-number v-model="form.top_n" :min="1" :max="20"/></el-form-item><el-form-item label="调仓频率"><el-select v-model="form.rebalance" aria-label="调仓频率"><el-option label="每日" value="daily"/><el-option label="每周" value="weekly"/><el-option label="每月" value="monthly"/></el-select></el-form-item></div><section class="dates"><div><strong>数据时间窗</strong><span>三个区间必须按时间先后排列</span></div><div v-for="row in [{label:'训练',start:'train_start',end:'train_end'},{label:'验证',start:'validation_start',end:'validation_end'},{label:'预测',start:'prediction_start',end:'prediction_end'}]" :key="row.label" class="date-row"><label>{{ row.label }}</label><el-date-picker v-model="form[row.start as keyof typeof form]" value-format="YYYY-MM-DD" placeholder="开始日期"/><span>至</span><el-date-picker v-model="form[row.end as keyof typeof form]" value-format="YYYY-MM-DD" placeholder="结束日期"/></div></section></el-form><template #footer><el-button @click="showCreate=false">取消</el-button><el-button type="primary" :loading="busy" data-testid="ml-save" @click="saveStrategy">冻结研究定义</el-button></template></el-dialog>
</section>
</template>

<style scoped>
.ml-workbench{min-width:0}.catalog-toolbar,.research-list{display:grid;gap:9px}.research-list{margin-top:14px}.research-list-item{background:transparent;border:1px solid var(--byq-border-subtle);border-radius:9px;color:var(--byq-text);cursor:pointer;display:grid;gap:7px;padding:12px;text-align:left;width:100%}.research-list-item:hover{background:var(--byq-surface-subtle)}.research-list-item.active{background:var(--byq-brand-soft);border-color:color-mix(in srgb,var(--byq-brand) 42%,var(--byq-border))}.list-head,.list-meta,.detail-heading,.result-intro{align-items:center;display:flex;gap:8px;justify-content:space-between;min-width:0}.list-head strong,.list-meta span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.method,.list-meta,.detail-heading p,.content-section p,.result-intro span,.run-list small,.help{color:var(--byq-text-muted);font-size:11px}.detail-heading{align-items:flex-start}.detail-heading>div>span{color:var(--byq-brand);font-size:10px;font-weight:800;letter-spacing:.08em}.detail-heading h3{font-size:19px;margin:3px 0}.detail-heading p,.content-section p{margin:0}.pipeline{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));list-style:none;margin:0 0 16px;padding:0}.pipeline li{align-items:flex-start;display:flex;gap:8px;min-width:0;position:relative}.pipeline li:not(:last-child):after{background:var(--byq-border);content:"";height:1px;left:30px;position:absolute;right:4px;top:13px}.pipeline b,.run-list>article>b{align-items:center;background:var(--byq-surface);border:1px solid var(--byq-border);border-radius:50%;color:var(--byq-text-muted);display:flex;flex:0 0 25px;font-size:11px;height:25px;justify-content:center;position:relative;z-index:1}.pipeline li>span{display:grid;gap:2px;position:relative;z-index:1}.pipeline strong{font-size:12px}.pipeline small{color:var(--byq-text-soft);font-size:10px}.pipeline .is-completed b{background:var(--byq-brand);border-color:var(--byq-brand);color:var(--byq-on-brand)}.pipeline .is-active b{border-color:var(--byq-brand);color:var(--byq-brand);box-shadow:0 0 0 3px var(--byq-brand-soft)}.pipeline .is-failed b{background:var(--byq-danger-soft);color:var(--byq-danger)}.next-step{align-items:center;background:var(--byq-brand-soft);border:1px solid color-mix(in srgb,var(--byq-brand) 24%,var(--byq-border));border-radius:10px;display:flex;gap:16px;justify-content:space-between;padding:14px 16px}.next-step>div:first-child{display:grid;gap:3px}.next-step>div:first-child>span{color:var(--byq-brand);font-size:10px;font-weight:800}.next-step p{color:var(--byq-text-muted);font-size:11px;margin:0}.next-actions{align-items:center;display:flex;gap:8px}.next-actions .el-select{min-width:190px}.research-tabs{margin-top:12px}.summary-grid,.metrics{display:grid;gap:9px;grid-template-columns:repeat(4,minmax(0,1fr))}.summary-grid>div{background:var(--byq-surface-subtle);border:1px solid var(--byq-border-subtle);border-radius:9px;display:grid;gap:5px;padding:12px}.summary-grid span,.metrics span{color:var(--byq-text-muted);font-size:11px}.summary-grid strong{font-size:13px}.summary-grid small{color:var(--byq-text-soft);font-size:10px}.content-section{border-top:1px solid var(--byq-border-subtle);margin-top:18px;padding-top:16px}.content-section h4{font-size:14px;margin:0}.periods{display:grid;gap:8px;grid-template-columns:repeat(3,minmax(0,1fr));margin:12px 0 0}.periods>div{border-left:2px solid var(--byq-border);display:grid;gap:4px;padding:4px 10px}.periods dt{color:var(--byq-text-muted);font-size:11px}.periods dd{font-size:12px;margin:0}.metrics{margin-top:12px}.metrics>div{display:grid;gap:4px}.metrics strong{font-size:17px}.result-intro{margin-bottom:10px}.result-intro>div{display:grid;gap:3px}.run-list{display:grid;gap:8px}.run-list article{align-items:center;border:1px solid var(--byq-border-subtle);border-radius:9px;display:grid;gap:10px;grid-template-columns:auto minmax(0,1fr) auto;padding:12px}.run-list article>div{display:grid;gap:3px}.technical{margin-top:12px}.technical :deep(.el-descriptions__content){overflow-wrap:anywhere}.create-intro{background:var(--byq-surface-subtle);border-radius:9px;margin-bottom:16px;padding:12px 14px}.create-intro p{color:var(--byq-text-muted);font-size:12px;margin:4px 0}.form-grid{display:grid;gap:12px;grid-template-columns:repeat(2,minmax(0,1fr))}.form-grid.three{grid-template-columns:repeat(3,minmax(0,1fr))}.form-grid :deep(.el-input-number),.form-grid :deep(.el-select){width:100%}.dates{border-top:1px solid var(--byq-border-subtle);display:grid;gap:10px;padding-top:14px}.dates>div:first-child{display:flex;justify-content:space-between}.dates>div:first-child span{color:var(--byq-text-muted);font-size:11px}.date-row{align-items:center;display:grid;gap:9px;grid-template-columns:44px minmax(0,1fr) auto minmax(0,1fr)}.date-row label{color:var(--byq-text-muted);font-size:12px;font-weight:700}.date-row :deep(.el-date-editor){width:100%}@media(max-width:1120px){.summary-grid,.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.pipeline small{display:none}}@media(max-width:760px){.next-step,.next-actions{align-items:stretch;flex-direction:column}.next-actions .el-select,.next-actions .el-button{width:100%}.pipeline{gap:4px}.pipeline li{align-items:center;display:grid;gap:5px;justify-items:center;text-align:center}.pipeline li:not(:last-child):after{left:calc(50% + 13px);right:calc(-50% + 13px)}.periods,.form-grid,.form-grid.three{grid-template-columns:1fr}.date-row{grid-template-columns:1fr}.date-row>span{display:none}}@media(max-width:480px){.summary-grid,.metrics{grid-template-columns:1fr}.list-meta time{display:none}}
</style>
