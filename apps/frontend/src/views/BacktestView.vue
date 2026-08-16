<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import type { EChartsOption } from "echarts";
import { getBacktest, listBacktests } from "@/api/quant";
import { useAuthStore } from "@/stores/auth";
import ChartWrapper from "@/components/charts/ChartWrapper.vue";
import MetricCard from "@/components/ui/MetricCard.vue";
import { formatChinaTime } from "@/time";

const auth = useAuthStore();
const loading = ref(true);
const error = ref("");
const backtests = ref<Array<Record<string, unknown>>>([]);
const selected = ref<Record<string, unknown> | null>(null);
const job = ref<Awaited<ReturnType<typeof getBacktest>> | null>(null);

const summary = computed(() => {
  const value = job.value as { summary?: Record<string, unknown> } | null;
  const selectedSummary = selected.value?.summary as Record<string, unknown> | undefined;
  return value?.summary ?? selectedSummary ?? {};
});

const equityOption = computed<EChartsOption>(() => ({
  title: { text: "Equity Curve" },
  tooltip: { trigger: "axis" },
  xAxis: { type: "category" as const, data: [] as string[] },
  yAxis: { type: "value" as const },
  series: [{ type: "line" as const, data: [] as number[] }],
}));

async function loadList() {
  loading.value = true;
  error.value = "";
  try {
    const response = await listBacktests(auth.token);
    backtests.value = response.backtests;
    if (backtests.value.length) {
      await select(backtests.value[0]);
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
  error.value = "";
  const jobId = row.job_id;
  if (typeof jobId !== "string") {
    error.value = "回测结果缺少 job_id";
    return;
  }
  try {
    job.value = await getBacktest(jobId, auth.token);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "读取回测任务失败";
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
        <el-empty v-if="!backtests.length" description="暂无回测结果" />
        <el-table v-else :data="backtests" highlight-current-row @current-change="select">
          <el-table-column prop="job_id" label="Job ID" min-width="220" show-overflow-tooltip />
          <el-table-column prop="status" label="状态" width="110" />
          <el-table-column label="创建时间" min-width="180">
            <template #default="{ row }">{{ formatChinaTime(row.created_at) }}</template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card shadow="never" class="backtest-detail-pane">
        <template #header>
          <div class="card-heading">
            <span class="card-title">回测详情</span>
            <small class="card-sub">{{ selected?.artifact_id ?? "未选择回测结果" }}</small>
          </div>
        </template>
        <p v-if="error" class="page-error">{{ error }}</p>
        <el-empty v-else-if="!job" description="请选择左侧回测结果" />
        <template v-else>
          <div class="metric-grid">
            <MetricCard label="Total Return" :value="String(summary.total_return ?? 'n/a')" />
            <MetricCard label="Max Drawdown" :value="String(summary.max_drawdown ?? 'n/a')" />
            <MetricCard label="Trade Count" :value="String(summary.trade_count ?? 'n/a')" />
            <MetricCard label="Status" :value="String(job.status ?? 'unknown')" />
          </div>
          <ChartWrapper :option="equityOption" empty />
          <details class="quant-result">
            <summary>原始任务投影</summary>
            <pre>{{ JSON.stringify(job, null, 2) }}</pre>
          </details>
        </template>
      </el-card>
    </div>
  </section>
</template>

<style scoped>
.backtest-workbench {
  display: grid;
  grid-template-columns: minmax(340px, 0.9fr) minmax(0, 1.1fr);
  gap: 1rem;
}

@media (max-width: 900px) {
  .backtest-workbench {
    grid-template-columns: 1fr;
  }
}
</style>
