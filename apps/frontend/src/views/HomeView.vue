<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { fetchDashboard, fetchHealth, fetchDataStatus } from "@/api/client";
import { getOperationsStatus } from "@/api/operations";
import { getSettingsStatus } from "@/api/settings";
import { listArtifacts } from "@/api/research";
import { useAuthStore } from "@/stores/auth";
import { formatChinaTime } from "@/time";

const auth = useAuthStore();
const loading = ref(true);
const error = ref("");
const dashboard = ref<Awaited<ReturnType<typeof fetchDashboard>> | null>(null);
const health = ref<Awaited<ReturnType<typeof fetchHealth>> | null>(null);
const dataStatus = ref<Awaited<ReturnType<typeof fetchDataStatus>> | null>(null);
const operations = ref<Awaited<ReturnType<typeof getOperationsStatus>> | null>(null);
const settings = ref<Awaited<ReturnType<typeof getSettingsStatus>> | null>(null);
const artifacts = ref<Array<Record<string, unknown>>>([]);

const summaryCards = computed(() => [
  { label: "Backend", value: String(dashboard.value?.resources.backend ?? "unknown") },
  { label: "Research Tasks", value: String(dashboard.value?.resources.counts?.tasks ?? "-") },
  { label: "Experiments", value: String(dashboard.value?.resources.counts?.experiments ?? "-") },
  { label: "策略/资产", value: String(dashboard.value?.resources.counts?.artifacts ?? artifacts.value.length) },
  { label: "回测任务", value: String(dashboard.value?.resources.counts?.backtests ?? "-") },
  { label: "运行时", value: String(operations.value?.runtime ?? "runtime-adapter") },
]);

onMounted(async () => {
  try {
    const token = auth.token;
    const [dashboardResult, healthResult, dataResult, operationsResult, settingsResult, artifactResult] =
      await Promise.allSettled([
        fetchDashboard(token),
        fetchHealth(token),
        fetchDataStatus(token),
        getOperationsStatus(token),
        getSettingsStatus(token),
        listArtifacts(),
      ]);
    if (dashboardResult.status === "fulfilled") dashboard.value = dashboardResult.value;
    if (healthResult.status === "fulfilled") health.value = healthResult.value;
    if (dataResult.status === "fulfilled") dataStatus.value = dataResult.value;
    if (operationsResult.status === "fulfilled") operations.value = operationsResult.value;
    if (settingsResult.status === "fulfilled") settings.value = settingsResult.value;
    if (artifactResult.status === "fulfilled") artifacts.value = artifactResult.value.artifacts;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载失败";
  } finally {
    loading.value = false;
  }
});

function kindLabel(kind: unknown): string {
  if (kind === "strategy_version") return "策略版本";
  if (kind === "backtest_result") return "回测结果";
  if (kind === "strategy_draft") return "策略草稿";
  if (kind === "factor_result") return "因子结果";
  return String(kind ?? "-");
}
</script>

<template>
  <section class="home-page">
    <div v-if="loading" class="base-loading">加载中...</div>
    <div v-else-if="error" class="base-error">{{ error }}</div>

    <template v-else>
      <div class="stats-strip">
        <div v-for="card in summaryCards" :key="card.label" class="stat-item">
          <span>{{ card.label }}</span>
          <strong>{{ card.value }}</strong>
        </div>
      </div>

      <div class="page-toolbar">
        <el-button type="primary" plain @click="$router.push('/agent')">开始研究</el-button>
        <el-button plain @click="$router.push('/strategy')">策略管理</el-button>
        <el-button plain @click="$router.push('/backtest')">回测管理</el-button>
        <el-button plain @click="$router.push('/stock-pool')">股票管理</el-button>
      </div>

      <div class="section-label-row">
        <span>最近研究资产</span>
        <small>来自 BYQ Artifact 列表</small>
      </div>

      <el-card shadow="never" class="top-band">
        <el-table v-if="artifacts.length" :data="artifacts" size="default">
          <el-table-column label="类型" width="130">
            <template #default="{ row }">
              <el-tag effect="light">{{ kindLabel(row.kind) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="artifact_id" label="Artifact ID" min-width="260" show-overflow-tooltip />
          <el-table-column prop="status" label="状态" width="120" />
          <el-table-column label="创建时间" min-width="190">
            <template #default="{ row }">{{ formatChinaTime(row.created_at) }}</template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="暂无研究资产" />
      </el-card>

      <div class="section-label-row">
        <span>服务健康</span>
        <small>Product API / Gateway 边界</small>
      </div>
      <el-card shadow="never" class="top-band">
        <div class="status-list">
          <div><span>Product Health</span><strong>{{ health?.status ?? "unknown" }}</strong></div>
          <div><span>模型提供方</span><strong>{{ settings?.model_provider.configured ? "configured" : "not_configured" }}</strong></div>
          <div><span>审批待处理</span><strong>{{ settings?.approval_inbox.pending ?? 0 }}</strong></div>
          <div><span>WorkflowTrace</span><strong>{{ operations?.observability.workflow_trace ?? "-" }}</strong></div>
          <div><span>审计</span><strong>{{ operations?.observability.audit ?? "-" }}</strong></div>
        </div>
      </el-card>
    </template>
  </section>
</template>
