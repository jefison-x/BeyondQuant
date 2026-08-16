<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { EChartsOption } from "echarts";
import {
  cancelBacktest,
  exportStrategyVersion,
  getBacktest,
  getResearchEntity,
  runBacktest,
} from "@/api/quant";
import { useAuthStore } from "@/stores/auth";
import ChartWrapper from "@/components/charts/ChartWrapper.vue";
import MetricCard from "@/components/ui/MetricCard.vue";

const auth = useAuthStore();
const props = defineProps<{ initialTab?: "factor" | "strategy" | "backtest" }>();
const tab = ref<"factor" | "strategy" | "backtest">(props.initialTab ?? "backtest");
const entityType = ref<"tasks" | "experiments" | "artifacts">("artifacts");
const entityId = ref("");
const artifactId = ref("");
const jobId = ref("");
const result = ref<unknown>(null);
const error = ref("");
const busy = ref(false);
const heading = computed(() =>
  tab.value === "strategy" ? "策略管理" : tab.value === "backtest" ? "回测管理" : "量化工作台",
);

watch(
  () => props.initialTab,
  (value) => {
    if (value) tab.value = value;
  },
);

const backtest = computed(() =>
  result.value as { status?: string; summary?: { total_return?: number; max_drawdown?: number } } | null,
);
const backtestStatus = computed(() => backtest.value?.status ?? "unknown");
const totalReturn = computed(() => backtest.value?.summary?.total_return ?? "n/a");
const maxDrawdown = computed(() => backtest.value?.summary?.max_drawdown ?? "n/a");
const equityOption = computed<EChartsOption>(() => ({
  title: { text: "Equity Curve" },
  xAxis: { type: "category" as const, data: [] as string[] },
  yAxis: { type: "value" as const },
  series: [{ type: "line" as const, data: [] as number[] }],
}));

async function loadEntity() {
  await run(async () => {
    result.value = await getResearchEntity(entityType.value, entityId.value, auth.token);
  });
}

async function exportVersion() {
  await run(async () => {
    result.value = await exportStrategyVersion(artifactId.value, auth.token);
  });
}

async function loadBacktest() {
  await run(async () => {
    result.value = await getBacktest(jobId.value, auth.token);
  });
}

async function runJob() {
  await run(async () => {
    result.value = await runBacktest(jobId.value, auth.token);
  });
}

async function cancelJob() {
  await run(async () => {
    result.value = await cancelBacktest(jobId.value, auth.token);
  });
}

async function run(operation: () => Promise<unknown>) {
  error.value = "";
  busy.value = true;
  try {
    result.value = await operation();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "操作失败";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section class="page-card">
    <h2>{{ heading }}</h2>
    <div class="quant-tabs">
      <button type="button" :class="{ active: tab === 'factor' }" @click="tab = 'factor'">Factor</button>
      <button type="button" :class="{ active: tab === 'strategy' }" @click="tab = 'strategy'">Strategy</button>
      <button type="button" :class="{ active: tab === 'backtest' }" @click="tab = 'backtest'">Backtest</button>
    </div>

    <div v-if="tab === 'factor'" class="quant-panel">
      <label>实体类型</label>
      <select v-model="entityType">
        <option value="tasks">ResearchTask</option>
        <option value="experiments">Experiment</option>
        <option value="artifacts">Artifact</option>
      </select>
      <input v-model="entityId" placeholder="实体 ID" />
      <button type="button" :disabled="busy" @click="loadEntity">查看</button>
    </div>

    <div v-else-if="tab === 'strategy'" class="quant-panel">
      <input v-model="artifactId" placeholder="StrategyVersion Artifact ID" />
      <button type="button" :disabled="busy" @click="exportVersion">导出版本</button>
    </div>

    <div v-else class="quant-panel">
      <input v-model="jobId" placeholder="Backtest Job ID" />
      <button type="button" :disabled="busy" @click="loadBacktest">查看</button>
      <button type="button" :disabled="busy" @click="runJob">运行</button>
      <button type="button" :disabled="busy" @click="cancelJob">取消</button>
    </div>

    <p v-if="error" class="page-error">{{ error }}</p>
    <div v-if="result && tab === 'backtest'" class="backtest-result">
      <div class="metric-grid">
        <MetricCard label="Status" :value="backtestStatus" />
        <MetricCard label="Total Return" :value="String(totalReturn)" />
        <MetricCard label="Max Drawdown" :value="String(maxDrawdown)" />
      </div>
      <ChartWrapper :option="equityOption" empty />
    </div>
    <pre v-else-if="result" class="quant-result">{{ JSON.stringify(result, null, 2) }}</pre>
  </section>
</template>
