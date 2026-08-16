<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { fetchDashboard, fetchHealth, fetchDataStatus } from "@/api/client";
import { getOperationsStatus } from "@/api/operations";
import { getSettingsStatus } from "@/api/settings";
import { listArtifacts } from "@/api/research";
import { useAuthStore } from "@/stores/auth";

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
  { label: "行情数据", value: String(dataStatus.value?.provider ?? "tushare") },
  { label: "数据迁移", value: String(dataStatus.value?.migration ?? "not_started") },
  { label: "运行时", value: String(operations.value?.runtime ?? "runtime-adapter") },
  { label: "存储", value: String(operations.value?.storage ?? "ready") },
  { label: "研究资产", value: String(artifacts.value.length) },
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
          <el-table-column prop="created_at" label="创建时间" min-width="190" />
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
