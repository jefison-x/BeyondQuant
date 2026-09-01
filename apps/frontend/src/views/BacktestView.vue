<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import type { EChartsOption } from "echarts";
import {
  cancelBacktest,
  createSignalProducerJob,
  deleteBacktest,
  getBacktest,
  getBacktestManifest,
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
import { backtestMetricLabel, shortReference, statusLabel } from "@/display";
import ManagementWorkspace from "@/components/layout/ManagementWorkspace.vue";
import ListFilterPagination from "@/components/ui/ListFilterPagination.vue";
import { useFilteredPagination } from "@/composables/useFilteredPagination";
import { createRequestId } from "@/utils/requestId";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
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
const detailLoading = ref(false);
const manifestLoading = ref(false);
const fullManifest = ref<Record<string, unknown> | null>(null);
const compareDetails = ref<Record<string, BacktestJob>>({});
let selectionSequence = 0;
let manifestRequest: Promise<void> | null = null;
let manifestRequestJobId = "";

const filteredBacktests = computed(() =>
  backtests.value.filter((row) => {
    const matchesStatus = !statusFilter.value || row.status === statusFilter.value;
    const matchesSearch = !search.value || String(row.job_id ?? "").includes(search.value);
    return matchesStatus && matchesSearch;
  }),
);
const backtestPages = useFilteredPagination(filteredBacktests, (row) => String(row.job_id ?? ""), 20);

const summary = computed<Record<string, unknown>>(() => {
  const value = result.value as unknown as Record<string, unknown> | null;
  return value ?? (job.value?.summary as Record<string, unknown> | undefined) ?? {};
});

const equityCurve = computed(() => result.value?.equity_curve ?? []);
const benchmarkCurve = computed(() => result.value?.benchmark_curve ?? []);

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
      name: "组合权益",
      type: "line" as const,
      data: equityCurve.value.map((point) => point.equity),
      showSymbol: false,
      smooth: true,
    },
    ...(benchmarkCurve.value.length
      ? [{
          name: `基准 ${result.value?.benchmark_symbol ?? ""}`,
          type: "line" as const,
          data: benchmarkCurve.value.map((point) => point.value),
          showSymbol: false,
          smooth: true,
        }]
      : []),
  ],
}));

const trades = computed(() => result.value?.trades ?? []);
const blockedTrades = computed(() => result.value?.blocked_trades ?? []);
const corporateEvents = computed(() => result.value?.corporate_action_events ?? []);
const dailyPositions = computed(() => result.value?.daily_positions ?? []);
const dailyReturns = computed(() => result.value?.daily_returns ?? []);
const backtestLogs = computed(() => result.value?.logs ?? []);
const tradePages = useFilteredPagination(trades, (row) => `${row.symbol ?? ""} ${row.timestamp ?? ""} ${row.order_type ?? ""}`, 50);
const dailyPages = useFilteredPagination(dailyPositions, (row) => `${row.trade_date ?? ""} ${JSON.stringify(row.positions ?? {})}`, 50);
const logPages = useFilteredPagination(backtestLogs, (row) => `${row.level ?? ""} ${row.message ?? ""}`, 50);
const strategySnapshot = computed(() => ({
  strategy_version_artifact_id: job.value?.strategy_version_artifact_id ?? result.value?.strategy_version_artifact_id ?? null,
  approval_artifact_id: job.value?.approval_artifact_id ?? result.value?.approval_artifact_id ?? null,
  input_manifest: fullManifest.value ?? job.value?.input_manifest ?? null,
}));
const displayedManifest = computed(() => fullManifest.value ?? job.value?.input_manifest ?? {});

function formatPercent(value: unknown) {
  if (value === null || value === undefined || value === "") return "-";
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
      const requested = typeof route.query.job === "string" ? route.query.job : "";
      const target = requested
        ? backtests.value.find((row) => String(row.job_id) === requested) ?? { job_id: requested }
        : selected.value
          ? backtests.value.find((row) => row.job_id === selected.value?.job_id)
          : backtests.value[0];
      if (target) void select(target, false);
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

async function select(row: Record<string, unknown>, updateRoute = true) {
  selected.value = row;
  job.value = row as unknown as BacktestJob;
  result.value = null;
  fullManifest.value = null;
  detailLoading.value = true;
  const sequence = ++selectionSequence;
  error.value = "";
  const jobId = row.job_id;
  if (typeof jobId !== "string") {
    error.value = "回测结果缺少 job_id";
    detailLoading.value = false;
    return;
  }
  if (activeTab.value === "snapshot" || activeTab.value === "manifest") void loadManifest();
  try {
    const [jobBody, resultBody] = await Promise.all([
      getBacktest(jobId, auth.token),
      row.status === "completed" ? getBacktestResult(jobId, auth.token) : Promise.resolve(null),
    ]);
    if (sequence !== selectionSequence) return;
    job.value = jobBody;
    result.value = resultBody?.result ?? null;
    if (updateRoute && route.query.job !== jobId) {
      await router.replace({ path: route.path, query: { ...route.query, job: jobId } });
    }
  } catch (exc) {
    if (sequence !== selectionSequence) return;
    error.value = exc instanceof Error ? exc.message : "读取回测任务失败";
  } finally {
    if (sequence === selectionSequence) detailLoading.value = false;
  }
}

function loadManifest(): Promise<void> {
  const jobId = String(job.value?.job_id ?? "");
  if (!jobId || fullManifest.value) return Promise.resolve();
  if (manifestRequest && manifestRequestJobId === jobId) return manifestRequest;
  manifestLoading.value = true;
  manifestRequestJobId = jobId;
  const request = getBacktestManifest(jobId, auth.token)
    .then((body) => {
      if (String(job.value?.job_id ?? "") === jobId) fullManifest.value = body.input_manifest;
    })
    .catch((exc: unknown) => {
      ElMessage.error(exc instanceof Error ? exc.message : "加载完整输入快照失败");
    })
    .finally(() => {
      if (manifestRequestJobId === jobId) {
        manifestLoading.value = false;
        manifestRequest = null;
        manifestRequestJobId = "";
      }
    });
  manifestRequest = request;
  return request;
}

async function openManifest() {
  await loadManifest();
  showManifest.value = true;
}

watch(activeTab, (tab) => {
  if (tab === "snapshot" || tab === "manifest") void loadManifest();
});

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

const compareJobs = computed(() => backtests.value
  .filter((row) => compareIds.value.includes(String(row.job_id)))
  .map((row) => compareDetails.value[String(row.job_id)] ?? row));

async function openCompare() {
  if (compareIds.value.length !== 2) return;
  try {
    const details = await Promise.all(compareIds.value.map((id) => getBacktest(id, auth.token)));
    compareDetails.value = Object.fromEntries(details.map((item) => [String(item.job_id), item]));
    showCompare.value = true;
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "加载回测对比失败");
  }
}

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
    rows.push({ label: backtestMetricLabel(key), a, b, diff });
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

function producerMissing(job: Record<string, unknown>): unknown {
  const readiness = job.readiness as Record<string, unknown> | undefined;
  return readiness?.missing_count ?? "-";
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
    const requestedStrategy = typeof route.query.strategy === "string" ? route.query.strategy : "";
    if (requestedStrategy) selectedOption.value = options.value.find(
      (item) => item.strategy_version_artifact_id === requestedStrategy,
    ) ?? null;
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
        trace_id: `signal-${createRequestId()}`,
        idempotency_key: createRequestId(),
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

function returnToConversation() {
  const session = typeof route.query.session === "string" ? route.query.session : "";
  void router.push({ path: "/agent", query: session ? { session } : {} });
}

function sendBacktestToAgent(intent: "analyze" | "optimize") {
  if (!job.value?.job_id) return;
  const reference = String(job.value.job_id);
  const draft = intent === "analyze"
    ? `请分析这次回测的收益、回撤、成交与风险，并说明最值得关注的改进方向。回测任务：${reference}`
    : `请基于这次回测先分析回撤来源，再提出控制最大回撤的策略优化方案；不要直接执行，先让我确认。回测任务：${reference}`;
  const session = typeof route.query.session === "string" ? route.query.session : "";
  void router.push({ path: "/agent", query: { ...(session ? { session } : { new: String(Date.now()) }), draft, context: "backtest" } });
}

function nestedReference(value: unknown, keys: string[]): string {
  if (!value || typeof value !== "object") return "";
  for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
    if (keys.includes(key) && typeof item === "string") return item;
    const nested = nestedReference(item, keys);
    if (nested) return nested;
  }
  return "";
}

function openPaperTrading() {
  const manifest = job.value?.input_manifest as Record<string, unknown> | undefined;
  const universe = manifest?.universe as Record<string, unknown> | undefined;
  const poolSnapshot = nestedReference(manifest, ["stock_pool_snapshot_id", "pool_snapshot_id"])
    || (typeof universe?.version_id === "string" ? universe.version_id : "");
  void router.push({ path: "/paper-trading", query: { ...(poolSnapshot ? { pool_snapshot: poolSnapshot } : {}), from: "backtest", job: String(job.value?.job_id ?? "") } });
}

onMounted(async () => { await loadList(); if (typeof route.query.strategy === "string") await openCreate(); });
</script>

<template>
  <section class="backtest-page">
    <div v-if="loading" class="base-loading" role="status" aria-live="polite">加载中...</div>
    <div v-else-if="error && !selected" class="base-error" role="alert">{{ error }}</div>

    <ManagementWorkspace
      v-else
      eyebrow="核心研究资产"
      title="回测任务与完整结果"
      description="沿不可变策略版本、审批与信号快照谱系复核收益、成交和执行假设。"
      catalog-label="回测任务"
      :count="filteredBacktests.length"
      @return="returnToConversation"
    >
      <template #return>返回投研对话</template>
      <template #actions>
        <el-button @click="loadList">刷新</el-button>
        <el-button type="primary" @click="openCreate">新建回测</el-button>
      </template>
      <template #summary>结果来自不可变输入和 BYQ 确定性引擎</template>
      <template #catalog>
      <el-card shadow="never" class="backtest-list-pane">
        <template #header>
          <div class="card-heading">
            <span class="card-title">回测结果</span>
            <small class="card-sub">收益、回撤、成交与执行证据</small>
          </div>
        </template>
        <div class="list-toolbar">
          <el-input v-model="search" placeholder="搜索回测任务编号" clearable />
          <el-select v-model="statusFilter" aria-label="回测状态筛选" placeholder="状态筛选" clearable>
            <el-option label="排队中" value="queued" />
            <el-option label="运行中" value="running" />
            <el-option label="已完成" value="completed" />
            <el-option label="已取消" value="cancelled" />
            <el-option label="失败" value="failed" />
          </el-select>
        </div>
        <el-empty v-if="!filteredBacktests.length" description="暂无回测结果" />
        <ListFilterPagination v-else v-model:page="backtestPages.page.value" query="" :page-size="backtestPages.pageSize.value" :total="backtestPages.total.value" label="回测任务分页" hide-search>
        <el-table
          class="desktop-catalog-table"
          :data="backtestPages.pageItems.value"
          highlight-current-row
          @current-change="select"
          @selection-change="onSelectionChange"
        >
          <el-table-column type="selection" width="42" />
          <el-table-column label="回测任务" min-width="150"><template #default="{ row }">{{ shortReference(row.job_id) }}</template></el-table-column>
          <el-table-column label="状态" width="100"><template #default="{ row }">{{ statusLabel(row.status) }}</template></el-table-column>
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
            v-for="row in backtestPages.pageItems.value"
            :key="String(row.job_id)"
            shadow="never"
            class="mobile-card"
            @click="select(row)"
          >
            <div class="mobile-card-head">
              <strong>回测 {{ shortReference(row.job_id) }}</strong>
              <el-tag size="small">{{ statusLabel(row.status) }}</el-tag>
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
        </ListFilterPagination>

        <div class="page-toolbar">
          <el-button
            :disabled="compareIds.length !== 2"
            :loading="false"
            @click="openCompare"
          >
            对比所选任务
          </el-button>
          <el-button @click="loadList">刷新</el-button>
        </div>
      </el-card>
      </template>

      <template #detail>
      <el-card v-loading="detailLoading" shadow="never" class="backtest-detail-pane">
        <template #header>
          <div class="card-heading">
            <span class="card-title">回测详情</span>
            <small class="card-sub">{{ selected?.job_id ?? "未选择回测结果" }}</small>
          </div>
        </template>
        <p v-if="error" class="page-error">{{ error }}</p>
        <el-empty v-else-if="!job" description="请选择左侧回测结果" />
        <template v-else>
          <div v-if="job.status === 'completed'" class="next-actions">
            <div><strong>接下来</strong><span>带着本次结果继续分析、优化，或基于同一股票池开始独立模拟操盘。</span></div>
            <el-button @click="sendBacktestToAgent('analyze')">让小巴分析</el-button>
            <el-button type="primary" @click="sendBacktestToAgent('optimize')">基于结果优化</el-button>
            <el-button @click="openCreate">再次回测</el-button>
            <el-button @click="openPaperTrading">进入模拟操盘</el-button>
          </div>
          <div class="metric-grid">
            <MetricCard label="累计收益" :value="formatPercent(summary.total_return)" />
            <MetricCard label="基准收益" :value="formatPercent(summary.benchmark_return)" />
            <MetricCard label="超额收益" :value="formatPercent(summary.excess_return)" />
            <MetricCard label="最大回撤" :value="formatPercent(summary.max_drawdown)" />
            <MetricCard label="成交笔数" :value="String(summary.trade_count ?? '-')" />
            <MetricCard label="被拦截交易" :value="String(summary.blocked_trade_count ?? '-')" />
            <MetricCard label="期末资产" :value="formatMoney(summary.final_value)" />
            <MetricCard label="状态" :value="statusLabel(job.status)" />
          </div>

          <el-tabs v-model="activeTab" class="result-tabs">
            <el-tab-pane label="权益曲线" name="equity" lazy>
              <ChartWrapper
                :option="equityOption"
                :empty="!equityCurve.length"
                aria-label="回测权益曲线"
                :summary="`展示 ${equityCurve.length} 个交易日的组合权益变化。`"
                empty-message="暂无权益曲线数据"
              />
            </el-tab-pane>
            <el-tab-pane label="交易明细" name="trades" lazy>
              <ListFilterPagination v-model:query="tradePages.query.value" v-model:page="tradePages.page.value" :page-size="tradePages.pageSize.value" :total="tradePages.total.value" placeholder="筛选股票、日期或方向" label="交易明细分页">
              <el-table :data="tradePages.pageItems.value" size="small" empty-text="暂无交易">
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
              </ListFilterPagination>
            </el-tab-pane>
            <el-tab-pane label="拦截明细" name="blocked" lazy>
              <el-table :data="blockedTrades" size="small" empty-text="暂无拦截">
                <el-table-column prop="symbol" label="证券" width="110" />
                <el-table-column prop="trade_date" label="日期" width="120" />
                <el-table-column prop="side" label="方向" width="80" />
                <el-table-column prop="reason_code" label="原因码" width="150" />
                <el-table-column prop="detail" label="说明" min-width="220" show-overflow-tooltip />
              </el-table>
            </el-tab-pane>
            <el-tab-pane label="公司行动" name="corporate" lazy>
              <el-table :data="corporateEvents" size="small" empty-text="暂无公司行动">
                <el-table-column prop="symbol" label="证券" width="110" />
                <el-table-column prop="ex_date" label="除权日" width="120" />
                <el-table-column prop="pay_date" label="派息日" width="120" />
                <el-table-column prop="share_listing_date" label="红股上市日" width="120" />
                <el-table-column label="原数量" width="100" align="right">
                  <template #default="{ row }">{{ row.old_quantity }}</template>
                </el-table-column>
                <el-table-column label="新数量" width="100" align="right">
                  <template #default="{ row }">{{ row.new_quantity }}</template>
                </el-table-column>
                <el-table-column label="现金分红" width="120" align="right">
                  <template #default="{ row }">{{ formatMoney(row.cash_dividend) }}</template>
                </el-table-column>
                <el-table-column label="结算" min-width="150">
                  <template #default="{ row }">现金{{ row.cash_settled ? '已到账' : '待到账' }} · 股份{{ row.shares_settled ? '已入账' : '待入账' }}</template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
            <el-tab-pane label="每日持仓&收益" name="daily" lazy>
              <ListFilterPagination v-model:query="dailyPages.query.value" v-model:page="dailyPages.page.value" :page-size="dailyPages.pageSize.value" :total="dailyPages.total.value" placeholder="筛选日期或持仓" label="每日持仓分页">
              <el-table :data="dailyPages.pageItems.value" size="small" empty-text="暂无每日数据">
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
              </ListFilterPagination>
            </el-tab-pane>
            <el-tab-pane label="日志输出" name="logs" lazy>
              <el-alert v-if="result?.log_truncated" title="日志已截断，仅显示前 500 条" type="warning" :closable="false" class="log-truncated" />
              <ListFilterPagination v-model:query="logPages.query.value" v-model:page="logPages.page.value" :page-size="logPages.pageSize.value" :total="logPages.total.value" placeholder="筛选日志级别或事件" label="回测日志分页">
              <el-table :data="logPages.pageItems.value" size="small" empty-text="暂无日志" max-height="420">
                <el-table-column prop="seq" label="#" width="70" />
                <el-table-column prop="level" label="级别" width="80" />
                <el-table-column prop="message" label="事件" min-width="180" />
                <el-table-column label="详情" min-width="320">
                  <template #default="{ row }">
                    <span class="muted">{{ JSON.stringify(Object.fromEntries(Object.entries(row).filter(([k]) => !["seq", "level", "message"].includes(k)))) }}</span>
                  </template>
                </el-table-column>
              </el-table>
              </ListFilterPagination>
            </el-tab-pane>
            <el-tab-pane label="技术详情" name="snapshot" lazy>
              <el-alert title="以下内容用于审计和复现，普通分析无需复制内部编号。" type="info" :closable="false" />
              <el-descriptions :column="1" border>
                <el-descriptions-item label="策略版本内部编号">
                  <code>{{ strategySnapshot.strategy_version_artifact_id ?? "-" }}</code>
                </el-descriptions-item>
                <el-descriptions-item label="审批记录内部编号">
                  <code>{{ strategySnapshot.approval_artifact_id ?? "-" }}</code>
                </el-descriptions-item>
              </el-descriptions>
              <div v-loading="manifestLoading"><pre class="quant-result">{{ JSON.stringify(strategySnapshot.input_manifest ?? {}, null, 2) }}</pre></div>
            </el-tab-pane>
            <el-tab-pane label="输入就绪检查" name="manifest" lazy>
              <el-button :loading="manifestLoading" @click="openManifest">查看输入就绪检查</el-button>
              <div v-loading="manifestLoading"><pre class="quant-result">{{ JSON.stringify(displayedManifest, null, 2) }}</pre></div>
            </el-tab-pane>
          </el-tabs>

          <el-dialog v-model="showManifest" title="输入就绪检查摘要" width="720px">
            <pre class="quant-result">{{ JSON.stringify(displayedManifest, null, 2) }}</pre>
          </el-dialog>
        </template>
      </el-card>
      </template>
    </ManagementWorkspace>

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
          :title="producerJob.status === 'waiting_for_data'
            ? `正在自动补全回测数据（含复权与公司行动） · 尚缺 ${String(producerMissing(producerJob))} 项`
            : `信号任务 ${String(producerJob.status)} · ${String(producerJob.job_id)}`"
          :type="producerJob.status === 'failed' ? 'error' : producerJob.status === 'completed' ? 'success' : 'info'"
          :closable="false"
          class="producer-status"
        />
        <div v-if="producerJob?.status === 'waiting_for_data'" class="wizard-hint">
          系统会按交易日历、证券上市/退市周期补齐日线、停牌状态与精确涨跌停价；数据完整后任务自动开始，无需重复提交。
        </div>
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
.next-actions { align-items: center; background: var(--byq-brand-soft); border: 1px solid var(--byq-border); border-radius: var(--byq-radius); display: flex; flex-wrap: wrap; gap: .5rem; margin-bottom: 1rem; padding: .75rem; }.next-actions > div { display: grid; flex: 1 1 260px; gap: .2rem; }.next-actions span { color: var(--byq-text-muted); font-size: 11px; }

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
  .desktop-catalog-table {
    display: none;
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
    min-width: 0;
  }

  .mobile-card-head strong { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

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
