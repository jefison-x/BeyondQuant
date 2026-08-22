<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import type { EChartsOption } from "echarts";
import {
  cancelBacktest,
  createSignalProducerJob,
  deleteBacktest,
  getBacktest,
  getBacktestResult,
  getSignalProducerJob,
  listBacktests,
  listBacktestOptions,
  listSignalSnapshots,
  runBacktest,
  submitBacktest,
} from "@/api/quant";
import { listStockPools } from "@/api/paper";
import type { BacktestJob, BacktestResult } from "@/api/types";
import { useAuthStore } from "@/stores/auth";
import ChartWrapper from "@/components/charts/ChartWrapper.vue";
import MetricCard from "@/components/ui/MetricCard.vue";
import { formatChinaTime } from "@/time";

const auth = useAuthStore();
const loading = ref(true);
const error = ref("");
const backtests = ref<Array<Record<string, unknown>>>([]);
const selected = ref<Record<string, unknown> | null>(null);
const job = ref<BacktestJob | null>(null);
const result = ref<BacktestResult | null>(null);
const statusFilter = ref("");
const search = ref("");
const busy = ref("");
const compareIds = ref<string[]>([]);
const showCompare = ref(false);
const showManifest = ref(false);
const activeTab = ref("equity");

const filteredBacktests = computed(() =>
  backtests.value.filter((row) => {
    const matchesStatus = !statusFilter.value || row.status === statusFilter.value;
    const matchesSearch = !search.value || String(row.job_id ?? "").includes(search.value);
    return matchesStatus && matchesSearch;
  }),
);

const summary = computed<Record<string, unknown>>(() => {
  const value = result.value as unknown as Record<string, unknown> | null;
  return value ?? (job.value?.summary as Record<string, unknown> | undefined) ?? {};
});

const equityCurve = computed(() => result.value?.equity_curve ?? []);

const equityOption = computed<EChartsOption>(() => ({
  title: { text: "权益曲线" },
  tooltip: { trigger: "axis" },
  grid: { left: 48, right: 24, top: 48, bottom: 40 },
  xAxis: {
    type: "category" as const,
    data: equityCurve.value.map((point) => point.trade_date),
  },
  yAxis: { type: "value" as const, scale: true },
  series: [
    {
      name: "Equity",
      type: "line" as const,
      data: equityCurve.value.map((point) => point.equity),
      showSymbol: false,
      smooth: true,
    },
  ],
}));

const trades = computed(() => result.value?.trades ?? []);
const blockedTrades = computed(() => result.value?.blocked_trades ?? []);
const corporateEvents = computed(() => result.value?.corporate_action_events ?? []);
const dailyPositions = computed(() => result.value?.daily_positions ?? []);
const dailyReturns = computed(() => result.value?.daily_returns ?? []);
const backtestLogs = computed(() => result.value?.logs ?? []);
const strategySnapshot = computed(() => ({
  strategy_version_artifact_id: job.value?.strategy_version_artifact_id ?? result.value?.strategy_version_artifact_id ?? null,
  approval_artifact_id: job.value?.approval_artifact_id ?? result.value?.approval_artifact_id ?? null,
  input_manifest: job.value?.input_manifest ?? null,
}));

function formatPercent(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) ? `${(number * 100).toFixed(2)}%` : "-";
}

function formatMoney(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString("zh-CN", { maximumFractionDigits: 2 }) : "-";
}

function summaryValue(row: Record<string, unknown>, key: string): unknown {
  const rowSummary = row.summary as Record<string, unknown> | undefined;
  return rowSummary?.[key];
}

function formatPositions(row: Record<string, unknown>): string {
  const positions = row.positions;
  if (!Array.isArray(positions) || positions.length === 0) return "空仓";
  return positions.map((p: Record<string, unknown>) => `${String(p.symbol)}×${String(p.quantity)}`).join("、");
}

function dailyReturnFor(tradeDate: unknown): unknown {
  const rows = dailyReturns.value as Array<Record<string, unknown>>;
  return rows.find((d) => d.trade_date === tradeDate)?.daily_return;
}

async function loadList() {
  loading.value = true;
  error.value = "";
  try {
    const response = await listBacktests(auth.token);
    backtests.value = response.backtests;
    if (backtests.value.length) {
      const first = backtests.value[0];
      if (!selected.value || backtests.value.some((row) => row.job_id === selected.value?.job_id)) {
        await select(first);
      }
    } else {
      selected.value = null;
      job.value = null;
      result.value = null;
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

async function select(row: Record<string, unknown>) {
  selected.value = row;
  job.value = null;
  result.value = null;
  error.value = "";
  const jobId = row.job_id;
  if (typeof jobId !== "string") {
    error.value = "回测结果缺少 job_id";
    return;
  }
  try {
    job.value = await getBacktest(jobId, auth.token);
    if (job.value.status === "completed") {
      const body = await getBacktestResult(jobId, auth.token);
      result.value = body.result;
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "读取回测任务失败";
  }
}

async function run(row: Record<string, unknown>) {
  const jobId = String(row.job_id ?? "");
  if (!jobId) return;
  busy.value = jobId;
  try {
    await runBacktest(jobId, auth.token);
    ElMessage.success("回测任务已启动");
    await loadList();
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "运行回测失败");
  } finally {
    busy.value = "";
  }
}

async function cancel(row: Record<string, unknown>) {
  const jobId = String(row.job_id ?? "");
  if (!jobId) return;
  busy.value = jobId;
  try {
    await cancelBacktest(jobId, auth.token);
    ElMessage.success("回测任务已取消");
    await loadList();
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "取消回测失败");
  } finally {
    busy.value = "";
  }
}

async function remove(row: Record<string, unknown>) {
  const jobId = String(row.job_id ?? "");
  if (!jobId) return;
  busy.value = jobId;
  try {
    await deleteBacktest(jobId, auth.token);
    ElMessage.success("回测任务已删除");
    if (selected.value && String(selected.value.job_id) === jobId) {
      selected.value = null;
      job.value = null;
      result.value = null;
    }
    await loadList();
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "删除回测失败");
  } finally {
    busy.value = "";
  }
}

function onSelectionChange(rows: Array<Record<string, unknown>>) {
  compareIds.value = rows.slice(0, 2).map((row) => String(row.job_id));
}

const compareJobs = computed(() =>
  backtests.value.filter((row) => compareIds.value.includes(String(row.job_id))),
);

const metricRows = computed(() => {
  const rows: Array<{ label: string; a: unknown; b: unknown; diff: string }> = [];
  const metrics = ["total_return", "max_drawdown", "trade_count", "blocked_trade_count", "final_value"];
  for (const key of metrics) {
    const aSummary = compareJobs.value[0]?.summary as Record<string, unknown> | undefined;
    const bSummary = compareJobs.value[1]?.summary as Record<string, unknown> | undefined;
    const a = aSummary?.[key];
    const b = bSummary?.[key];
    const diff =
      typeof a === "number" && typeof b === "number"
        ? (Number(b) - Number(a)).toFixed(6)
        : "-";
    rows.push({ label: key, a, b, diff });
  }
  return rows;
});

const executionRuleRows = computed(() => {
  const rows: Array<{ label: string; a: unknown; b: unknown }> = [];
  const labels = ["initial_capital", "commission_rate", "stamp_tax_rate", "slippage_rate", "lot_size", "max_positions", "a_share_rules", "limit_threshold"];
  for (const label of labels) {
    const aExecution = (compareJobs.value[0]?.input_manifest as Record<string, unknown> | undefined)?.execution as Record<string, unknown> | undefined;
    const bExecution = (compareJobs.value[1]?.input_manifest as Record<string, unknown> | undefined)?.execution as Record<string, unknown> | undefined;
    const a = aExecution?.[label];
    const b = bExecution?.[label];
    rows.push({ label, a, b });
  }
  return rows;
});

const showCreate = ref(false);
const creating = ref(false);
const options = ref<Array<Record<string, unknown>>>([]);
const snapshots = ref<Array<Record<string, unknown>>>([]);
const selectedOption = ref<Record<string, unknown> | null>(null);
const selectedSnapshot = ref<Record<string, unknown> | null>(null);
const pools = ref<Array<Record<string, unknown>>>([]);
const selectedPool = ref<Record<string, unknown> | null>(null);
const signalStartDate = ref("");
const signalEndDate = ref("");
const signalQuantity = ref(100);
const producingSignals = ref(false);
const producerJob = ref<Record<string, unknown> | null>(null);

const matchingSnapshots = computed(() => {
  const versionId = selectedOption.value?.strategy_version_artifact_id;
  if (!versionId) return [];
  return snapshots.value.filter((snap) => {
    const content = snap.content as Record<string, unknown> | undefined;
    const strategy = content?.strategy as Record<string, unknown> | undefined;
    return strategy?.strategy_version_artifact_id === versionId;
  });
});

function snapshotProducer(snap: Record<string, unknown>): string {
  const content = snap.content as Record<string, unknown> | undefined;
  const source = content?.source as Record<string, unknown> | undefined;
  return String(source?.producer ?? "unknown");
}

function snapshotExecution(snap: Record<string, unknown>, key: string): unknown {
  const content = snap.content as Record<string, unknown> | undefined;
  const execution = content?.execution as Record<string, unknown> | undefined;
  return execution?.[key] ?? "-";
}

async function openCreate() {
  showCreate.value = true;
  selectedOption.value = null;
  selectedSnapshot.value = null;
  selectedPool.value = null;
  producerJob.value = null;
  try {
    const [o, s, p] = await Promise.all([
      listBacktestOptions(auth.token), listSignalSnapshots(auth.token), listStockPools(auth.token),
    ]);
    options.value = o.options ?? [];
    snapshots.value = s.snapshots ?? [];
    pools.value = (p.pools ?? []).filter((item) => item.status === "active" && item.current_snapshot_id);
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "加载回测选项失败");
  }
}

async function produceSignals() {
  const opt = selectedOption.value;
  const pool = selectedPool.value;
  if (!opt || !pool || !signalStartDate.value || !signalEndDate.value) {
    ElMessage.warning("请选择策略、股票池和信号日期范围");
    return;
  }
  producingSignals.value = true;
  producerJob.value = null;
  try {
    const created = await createSignalProducerJob(
      {
        task_id: opt.task_id,
        strategy_version_artifact_id: opt.strategy_version_artifact_id,
        stock_pool_snapshot_id: pool.current_snapshot_id,
        start_date: signalStartDate.value,
        end_date: signalEndDate.value,
        execution: {
          initial_capital: 100000,
          commission_rate: 0.0003,
          stamp_tax_rate: 0.001,
          slippage_rate: 0,
          lot_size: 100,
          max_positions: 10,
          a_share_rules: true,
          max_runtime_seconds: 10,
          max_attempts: 2,
        },
        order_quantity: signalQuantity.value,
        trace_id: `signal-${crypto.randomUUID()}`,
        idempotency_key: crypto.randomUUID(),
      },
      auth.token,
    );
    producerJob.value = created.job;
    const jobId = String(created.job.job_id ?? "");
    for (let attempt = 0; attempt < 45; attempt += 1) {
      if (attempt) await new Promise((resolve) => window.setTimeout(resolve, 1000));
      const response = await getSignalProducerJob(jobId, auth.token);
      producerJob.value = response.job;
      if (response.job.status === "completed") {
        const body = await listSignalSnapshots(auth.token);
        snapshots.value = body.snapshots ?? [];
        selectedSnapshot.value = snapshots.value.find(
          (item) => item.artifact_id === response.job.result_artifact_id,
        ) ?? null;
        ElMessage.success("信号快照已生成并冻结");
        return;
      }
      if (response.job.status === "failed") {
        throw new Error(String(response.job.error_detail ?? "信号生成失败"));
      }
    }
    throw new Error("信号任务仍在运行，请稍后重新打开向导查看");
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "信号生成失败");
  } finally {
    producingSignals.value = false;
  }
}

async function submitCreate() {
  const opt = selectedOption.value;
  const snap = selectedSnapshot.value;
  if (!opt || !snap) return;
  creating.value = true;
  const stamp = Date.now();
  try {
    await submitBacktest(
      {
        task_id: opt.task_id,
        strategy_version_artifact_id: opt.strategy_version_artifact_id,
        approval_artifact_id: opt.approval_artifact_id,
        signal_snapshot_artifact_id: snap.artifact_id,
        trace_id: `byq-wizard-${stamp}`,
        idempotency_key: `wizard-${stamp}`,
      },
      auth.token,
    );
    ElMessage.success("回测已创建并排队");
    showCreate.value = false;
    await loadList();
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "创建回测失败");
  } finally {
    creating.value = false;
  }
}

onMounted(loadList);
</script>

<template>
  <section class="backtest-page">
    <div v-if="loading" class="base-loading">加载中...</div>
    <div v-else-if="error && !selected" class="base-error">{{ error }}</div>

    <div v-else class="backtest-workbench">
      <el-card shadow="never" class="backtest-list-pane">
        <template #header>
          <div class="card-heading">
            <span class="card-title">回测结果</span>
            <small class="card-sub">Artifact kind: backtest_result</small>
          </div>
        </template>
        <div class="list-toolbar">
          <el-input v-model="search" placeholder="搜索 Job ID" clearable />
          <el-select v-model="statusFilter" aria-label="回测状态筛选" placeholder="状态筛选" clearable>
            <el-option label="queued" value="queued" />
            <el-option label="running" value="running" />
            <el-option label="completed" value="completed" />
            <el-option label="cancelled" value="cancelled" />
            <el-option label="failed" value="failed" />
          </el-select>
          <el-button type="primary" size="small" @click="openCreate">新建回测</el-button>
        </div>
        <el-empty v-if="!filteredBacktests.length" description="暂无回测结果" />
        <el-table
          v-else
          :data="filteredBacktests"
          highlight-current-row
          @current-change="select"
          @selection-change="onSelectionChange"
        >
          <el-table-column type="selection" width="42" />
          <el-table-column prop="job_id" label="Job ID" min-width="220" show-overflow-tooltip />
          <el-table-column prop="status" label="状态" width="100" />
          <el-table-column label="收益" width="90" align="right">
            <template #default="{ row }">{{ formatPercent(summaryValue(row, "total_return")) }}</template>
          </el-table-column>
          <el-table-column label="回撤" width="90" align="right">
            <template #default="{ row }">{{ formatPercent(summaryValue(row, "max_drawdown")) }}</template>
          </el-table-column>
          <el-table-column label="创建时间" min-width="170">
            <template #default="{ row }">{{ formatChinaTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="190" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="row.status === 'queued' || row.status === 'failed'"
                size="small"
                type="primary"
                :loading="busy === row.job_id"
                @click.stop="run(row)"
              >
                运行
              </el-button>
              <el-button
                v-if="row.status === 'queued' || row.status === 'running'"
                size="small"
                type="danger"
                plain
                :loading="busy === row.job_id"
                @click.stop="cancel(row)"
              >
                取消
              </el-button>
              <el-button
                v-if="['completed', 'cancelled', 'failed'].includes(String(row.status))"
                size="small"
                type="danger"
                link
                :loading="busy === row.job_id"
                @click.stop="remove(row)"
              >
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="mobile-list">
          <el-card
            v-for="row in filteredBacktests"
            :key="String(row.job_id)"
            shadow="never"
            class="mobile-card"
            @click="select(row)"
          >
            <div class="mobile-card-head">
              <strong>{{ row.job_id }}</strong>
              <el-tag size="small">{{ row.status }}</el-tag>
            </div>
            <div class="mobile-card-meta">
              <span>收益 {{ formatPercent(summaryValue(row, "total_return")) }}</span>
              <span>{{ formatChinaTime(row.created_at) }}</span>
            </div>
            <div v-if="['completed', 'cancelled', 'failed'].includes(String(row.status))" class="mobile-card-actions">
              <el-button size="small" type="danger" link :loading="busy === row.job_id" @click.stop="remove(row)">
                删除
              </el-button>
            </div>
          </el-card>
        </div>

        <div class="page-toolbar">
          <el-button
            :disabled="compareIds.length !== 2"
            :loading="false"
            @click="showCompare = true"
          >
            对比所选任务
          </el-button>
          <el-button @click="loadList">刷新</el-button>
        </div>
      </el-card>

      <el-card shadow="never" class="backtest-detail-pane">
        <template #header>
          <div class="card-heading">
            <span class="card-title">回测详情</span>
            <small class="card-sub">{{ selected?.job_id ?? "未选择回测结果" }}</small>
          </div>
        </template>
        <p v-if="error" class="page-error">{{ error }}</p>
        <el-empty v-else-if="!job" description="请选择左侧回测结果" />
        <template v-else>
          <div class="metric-grid">
            <MetricCard label="Total Return" :value="formatPercent(summary.total_return)" />
            <MetricCard label="Max Drawdown" :value="formatPercent(summary.max_drawdown)" />
            <MetricCard label="Trade Count" :value="String(summary.trade_count ?? '-')" />
            <MetricCard label="Blocked Trades" :value="String(summary.blocked_trade_count ?? '-')" />
            <MetricCard label="Final Value" :value="formatMoney(summary.final_value)" />
            <MetricCard label="Status" :value="String(job.status ?? 'unknown')" />
          </div>

          <el-tabs v-model="activeTab" class="result-tabs">
            <el-tab-pane label="权益曲线" name="equity">
              <ChartWrapper :option="equityOption" :empty="!equityCurve.length" />
            </el-tab-pane>
            <el-tab-pane label="交易明细" name="trades">
              <el-table :data="trades" size="small" empty-text="暂无交易">
                <el-table-column prop="timestamp" label="日期" width="120" />
                <el-table-column prop="symbol" label="证券" width="110" />
                <el-table-column prop="order_type" label="方向" width="80" />
                <el-table-column prop="quantity" label="数量" width="90" align="right" />
                <el-table-column label="成交价" width="110" align="right">
                  <template #default="{ row }">{{ formatMoney(row.price) }}</template>
                </el-table-column>
                <el-table-column label="佣金" width="100" align="right">
                  <template #default="{ row }">{{ formatMoney(row.commission) }}</template>
                </el-table-column>
                <el-table-column label="税费" width="100" align="right">
                  <template #default="{ row }">{{ formatMoney(row.tax) }}</template>
                </el-table-column>
                <el-table-column label="已实现盈亏" width="110" align="right">
                  <template #default="{ row }">{{ formatMoney(row.realized_pnl) }}</template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
            <el-tab-pane label="拦截明细" name="blocked">
              <el-table :data="blockedTrades" size="small" empty-text="暂无拦截">
                <el-table-column prop="symbol" label="证券" width="110" />
                <el-table-column prop="trade_date" label="日期" width="120" />
                <el-table-column prop="side" label="方向" width="80" />
                <el-table-column prop="reason_code" label="原因码" width="150" />
                <el-table-column prop="detail" label="说明" min-width="220" show-overflow-tooltip />
              </el-table>
            </el-tab-pane>
            <el-tab-pane label="公司行动" name="corporate">
              <el-table :data="corporateEvents" size="small" empty-text="暂无公司行动">
                <el-table-column prop="symbol" label="证券" width="110" />
                <el-table-column prop="ex_date" label="除权日" width="120" />
                <el-table-column label="原数量" width="100" align="right">
                  <template #default="{ row }">{{ row.old_quantity }}</template>
                </el-table-column>
                <el-table-column label="新数量" width="100" align="right">
                  <template #default="{ row }">{{ row.new_quantity }}</template>
                </el-table-column>
                <el-table-column label="现金分红" width="120" align="right">
                  <template #default="{ row }">{{ formatMoney(row.cash_dividend) }}</template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
            <el-tab-pane label="每日持仓&收益" name="daily">
              <el-table :data="dailyPositions" size="small" empty-text="暂无每日数据">
                <el-table-column prop="trade_date" label="日期" width="120" />
                <el-table-column label="持仓" min-width="260">
                  <template #default="{ row }">
                    {{ formatPositions(row) }}
                  </template>
                </el-table-column>
                <el-table-column label="日收益" width="110" align="right">
                  <template #default="{ row }">{{ formatPercent(dailyReturnFor(row.trade_date)) }}</template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
            <el-tab-pane label="日志输出" name="logs">
              <el-alert v-if="result?.log_truncated" title="日志已截断，仅显示前 500 条" type="warning" :closable="false" class="log-truncated" />
              <el-table :data="backtestLogs" size="small" empty-text="暂无日志" max-height="420">
                <el-table-column prop="seq" label="#" width="70" />
                <el-table-column prop="level" label="级别" width="80" />
                <el-table-column prop="message" label="事件" min-width="180" />
                <el-table-column label="详情" min-width="320">
                  <template #default="{ row }">
                    <span class="muted">{{ JSON.stringify(Object.fromEntries(Object.entries(row).filter(([k]) => !["seq", "level", "message"].includes(k)))) }}</span>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
            <el-tab-pane label="策略快照" name="snapshot">
              <el-descriptions :column="1" border>
                <el-descriptions-item label="策略版本工件">
                  <code>{{ strategySnapshot.strategy_version_artifact_id ?? "-" }}</code>
                </el-descriptions-item>
                <el-descriptions-item label="审批工件">
                  <code>{{ strategySnapshot.approval_artifact_id ?? "-" }}</code>
                </el-descriptions-item>
              </el-descriptions>
              <pre class="quant-result">{{ JSON.stringify(strategySnapshot.input_manifest ?? {}, null, 2) }}</pre>
            </el-tab-pane>
            <el-tab-pane label="输入清单 / Preflight" name="manifest">
              <el-button @click="showManifest = true">查看 Preflight</el-button>
              <pre class="quant-result">{{ JSON.stringify(job.input_manifest, null, 2) }}</pre>
            </el-tab-pane>
          </el-tabs>

          <el-dialog v-model="showManifest" title="Preflight 摘要" width="720px">
            <pre class="quant-result">{{ JSON.stringify(job.input_manifest, null, 2) }}</pre>
          </el-dialog>
        </template>
      </el-card>
    </div>

    <el-dialog v-model="showCompare" title="回测对比" width="min(960px, 94vw)">
      <el-tabs>
        <el-tab-pane label="指标差异">
          <el-table :data="metricRows" size="small">
            <el-table-column prop="label" label="指标" width="160" />
            <el-table-column label="任务 A" min-width="160">
              <template #default="{ row }">{{ row.a ?? "-" }}</template>
            </el-table-column>
            <el-table-column label="任务 B" min-width="160">
              <template #default="{ row }">{{ row.b ?? "-" }}</template>
            </el-table-column>
            <el-table-column prop="diff" label="差异 B - A" width="140" />
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="成交规则">
          <el-table :data="executionRuleRows" size="small">
            <el-table-column prop="label" label="规则" width="180" />
            <el-table-column label="任务 A" min-width="180">
              <template #default="{ row }">{{ row.a ?? "-" }}</template>
            </el-table-column>
            <el-table-column label="任务 B" min-width="180">
              <template #default="{ row }">{{ row.b ?? "-" }}</template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-dialog>
    <el-dialog v-model="showCreate" title="生成信号并新建回测" width="min(700px, 94vw)">
      <el-form label-position="top">
        <el-form-item label="已批准策略版本">
          <el-select v-model="selectedOption" filterable placeholder="选择已批准的策略版本" style="width: 100%">
            <el-option
              v-for="opt in options"
              :key="String(opt.strategy_version_artifact_id)"
              :value="opt"
              :label="`${String(opt.strategy_id)} · ${String(opt.strategy_version_id).slice(0, 8)}`"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="信号快照（ADR-0017 冻结输入）">
          <el-select
            v-model="selectedSnapshot"
            filterable
            placeholder="选择匹配该策略的信号快照"
            style="width: 100%"
            :disabled="!selectedOption"
          >
            <el-option
              v-for="snap in matchingSnapshots"
              :key="String(snap.artifact_id)"
              :value="snap"
              :label="`${String(snap.artifact_id).slice(0, 18)} · ${snapshotProducer(snap)}`"
            />
          </el-select>
          <div class="wizard-hint">可选择已有快照，或在下方用 ADR-0023 隔离运行时生成。</div>
        </el-form-item>
        <el-divider content-position="left">隔离生成信号</el-divider>
        <el-form-item label="不可变股票池快照">
          <el-select v-model="selectedPool" filterable placeholder="选择活动股票池" style="width: 100%">
            <el-option
              v-for="pool in pools"
              :key="String(pool.pool_id)"
              :value="pool"
              :label="`${String(pool.name)} · ${String(pool.member_count ?? 0)} 只`"
            />
          </el-select>
        </el-form-item>
        <div class="signal-range-grid">
          <el-form-item label="开始日期">
            <el-date-picker v-model="signalStartDate" type="date" value-format="YYYY-MM-DD" placeholder="YYYY-MM-DD" />
          </el-form-item>
          <el-form-item label="结束日期">
            <el-date-picker v-model="signalEndDate" type="date" value-format="YYYY-MM-DD" placeholder="YYYY-MM-DD" />
          </el-form-item>
          <el-form-item label="每次信号数量">
            <el-input-number v-model="signalQuantity" :min="100" :step="100" />
          </el-form-item>
        </div>
        <el-button
          type="success"
          plain
          :loading="producingSignals"
          :disabled="!selectedOption || !selectedPool || !signalStartDate || !signalEndDate"
          @click="produceSignals"
        >
          隔离执行并冻结信号快照
        </el-button>
        <el-alert
          v-if="producerJob"
          :title="`信号任务 ${String(producerJob.status)} · ${String(producerJob.job_id)}`"
          :type="producerJob.status === 'failed' ? 'error' : producerJob.status === 'completed' ? 'success' : 'info'"
          :closable="false"
          class="producer-status"
        />
        <template v-if="selectedSnapshot">
          <el-divider content-position="left">冻结执行参数</el-divider>
          <el-descriptions :column="2" size="small" border>
            <el-descriptions-item label="初始资金">{{ snapshotExecution(selectedSnapshot, "initial_capital") }}</el-descriptions-item>
            <el-descriptions-item label="手续费率">{{ snapshotExecution(selectedSnapshot, "commission_rate") }}</el-descriptions-item>
            <el-descriptions-item label="印花税率">{{ snapshotExecution(selectedSnapshot, "stamp_tax_rate") }}</el-descriptions-item>
            <el-descriptions-item label="整手">{{ snapshotExecution(selectedSnapshot, "lot_size") }}</el-descriptions-item>
          </el-descriptions>
          <div class="wizard-hint">执行参数随快照冻结，向导不可修改（不可变输入）。</div>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="creating" :disabled="!selectedOption || !selectedSnapshot" @click="submitCreate">
          创建回测
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.backtest-workbench {
  display: grid;
  grid-template-columns: minmax(360px, 0.9fr) minmax(0, 1.1fr);
  gap: 1rem;
}

.list-toolbar {
  display: grid;
  gap: 0.5rem;
  grid-template-columns: 1fr 150px;
  margin-bottom: 0.75rem;
}

.page-toolbar {
  display: flex;
  gap: 0.5rem;
  justify-content: flex-end;
  margin-top: 0.75rem;
}

.metric-grid {
  display: grid;
  gap: 0.75rem;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-bottom: 1rem;
}

.result-tabs {
  min-height: 320px;
}

.quant-result {
  background: var(--byq-surface-subtle);
  border-radius: var(--byq-radius-sm);
  font-size: 12px;
  margin-top: 0.75rem;
  max-height: 420px;
  overflow: auto;
  padding: 0.75rem;
  white-space: pre-wrap;
}

.wizard-hint {
  color: var(--byq-text-muted);
  font-size: 12px;
  margin-top: 0.35rem;
}

.signal-range-grid {
  display: grid;
  gap: 0.75rem;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.signal-range-grid :deep(.el-date-editor) {
  width: 100%;
}

.producer-status {
  margin-top: 0.75rem;
}

.mobile-list {
  display: none;
}

@media (max-width: 900px) {
  .backtest-workbench {
    grid-template-columns: 1fr;
  }

  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .signal-range-grid {
    grid-template-columns: 1fr;
  }

  .mobile-list {
    display: grid;
    gap: 0.6rem;
    margin-top: 0.75rem;
  }

  .mobile-card {
    cursor: pointer;
  }

  .mobile-card-head {
    align-items: center;
    display: flex;
    gap: 0.5rem;
    justify-content: space-between;
  }

  .mobile-card-meta {
    color: var(--byq-text-muted);
    display: flex;
    font-size: 12px;
    gap: 0.75rem;
    justify-content: space-between;
    margin-top: 0.4rem;
  }
}
</style>
