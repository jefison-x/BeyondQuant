<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { fetchDashboard, fetchHealth, fetchDataStatus } from "@/api/client";
import { getOperationsStatus } from "@/api/operations";
import { getSettingsStatus } from "@/api/settings";
import { listArtifacts } from "@/api/research";
import { listBacktests } from "@/api/quant";
import { useAuthStore } from "@/stores/auth";
import { formatChinaTime } from "@/time";
import { shortReference, statusLabel } from "@/display";

const auth = useAuthStore();
const loading = ref(true);
const error = ref("");
const dashboard = ref<Awaited<ReturnType<typeof fetchDashboard>> | null>(null);
const health = ref<Awaited<ReturnType<typeof fetchHealth>> | null>(null);
const dataStatus = ref<Awaited<ReturnType<typeof fetchDataStatus>> | null>(null);
const operations = ref<Awaited<ReturnType<typeof getOperationsStatus>> | null>(null);
const settings = ref<Awaited<ReturnType<typeof getSettingsStatus>> | null>(null);
const artifacts = ref<Array<Record<string, unknown>>>([]);
const backtests = ref<Array<Record<string, unknown>>>([]);
const failedResources = ref<string[]>([]);

const summaryCards = computed(() => [
  { label: "核心服务", value: statusLabel(dashboard.value?.resources.backend) },
  { label: "研究任务", value: String(dashboard.value?.resources.counts?.tasks ?? "-") },
  { label: "研究方案", value: String(dashboard.value?.resources.counts?.experiments ?? "-") },
  { label: "研究成果", value: String(dashboard.value?.resources.counts?.artifacts ?? artifacts.value.length) },
  { label: "回测任务", value: String(dashboard.value?.resources.counts?.backtests ?? "-") },
  { label: "智能研究服务", value: statusLabel(operations.value?.runtime.runtime.status ?? health.value?.status) },
]);

const failedResourceLabel: Record<string, string> = {
  dashboard: "工作台", health: "服务状态", data: "行情状态", operations: "运行状态",
  settings: "个人设置", artifacts: "研究成果", backtests: "回测记录",
};

onMounted(async () => {
  try {
    const token = auth.token;
    const [dashboardResult, healthResult, dataResult, operationsResult, settingsResult, artifactResult, backtestResult] =
      await Promise.allSettled([
        fetchDashboard(token),
        fetchHealth(token),
        fetchDataStatus(token),
        auth.isAdmin ? getOperationsStatus(token) : Promise.resolve(null),
        getSettingsStatus(token),
        listArtifacts(),
        listBacktests(token),
      ]);
    if (dashboardResult.status === "fulfilled") dashboard.value = dashboardResult.value;
    if (healthResult.status === "fulfilled") health.value = healthResult.value;
    if (dataResult.status === "fulfilled") dataStatus.value = dataResult.value;
    if (operationsResult.status === "fulfilled" && operationsResult.value) operations.value = operationsResult.value;
    if (settingsResult.status === "fulfilled") settings.value = settingsResult.value;
    if (artifactResult.status === "fulfilled") artifacts.value = artifactResult.value.artifacts;
    if (backtestResult.status === "fulfilled") backtests.value = backtestResult.value.backtests;
    const checks: Array<[string, PromiseSettledResult<unknown>]> = [
      ["dashboard", dashboardResult as PromiseSettledResult<unknown>],
      ["health", healthResult as PromiseSettledResult<unknown>],
      ["data", dataResult as PromiseSettledResult<unknown>],
      ...(auth.isAdmin
        ? [["operations", operationsResult as PromiseSettledResult<unknown>] as [string, PromiseSettledResult<unknown>]]
        : []),
      ["settings", settingsResult as PromiseSettledResult<unknown>],
      ["artifacts", artifactResult as PromiseSettledResult<unknown>],
      ["backtests", backtestResult as PromiseSettledResult<unknown>],
    ];
    failedResources.value = checks
      .filter((entry) => entry[1].status === "rejected")
      .map((entry) => entry[0]);
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
    <div v-if="loading" class="base-loading" role="status" aria-live="polite">加载中...</div>
    <div v-else-if="error" class="base-error" role="alert">{{ error }}</div>

    <template v-else>
      <el-alert
        v-if="failedResources.length"
        type="warning"
        :closable="false"
        :title="`部分内容暂时无法加载：${failedResources.map((item) => failedResourceLabel[item] ?? item).join('、')}`"
      />

      <div class="stats-strip">
        <div v-for="card in summaryCards" :key="card.label" class="stat-item">
          <span>{{ card.label }}</span>
          <strong>{{ card.value }}</strong>
        </div>
      </div>

      <el-card shadow="never" class="top-band">
        <template #header>
          <div class="card-title">使用状态</div>
        </template>
        <div class="resource-bars">
          <div>
            <span>核心服务</span>
            <el-progress :percentage="dashboard?.resources.backend === 'ok' ? 100 : 0" />
          </div>
          <div>
            <span>数据准备</span>
            <el-progress :percentage="dataStatus?.migration === 'not_started' ? 0 : 100" />
          </div>
          <div>
            <span>存储</span>
            <el-progress :percentage="operations ? (operations.database.status === 'ready' ? 100 : 0) : (health?.status === 'ok' ? 100 : 0)" />
          </div>
        </div>
      </el-card>

      <div class="page-toolbar">
        <el-button type="primary" plain @click="$router.push('/agent')">开始研究</el-button>
        <el-button plain @click="$router.push('/strategy')">策略管理</el-button>
        <el-button plain @click="$router.push('/backtest')">回测管理</el-button>
        <el-button plain @click="$router.push('/stock-pool')">股票管理</el-button>
      </div>

      <div class="section-label-row">
        <span>最近研究资产</span>
        <small>可继续查看、审批或用于回测</small>
      </div>

      <el-card shadow="never" class="top-band">
        <el-table v-if="artifacts.length" :data="artifacts" size="default">
          <el-table-column label="类型" width="130">
            <template #default="{ row }">
              <el-tag effect="light">{{ kindLabel(row.kind) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="记录编号" min-width="180"><template #default="{ row }">{{ shortReference(row.artifact_id) }}</template></el-table-column>
          <el-table-column label="状态" width="120"><template #default="{ row }">{{ statusLabel(row.status) }}</template></el-table-column>
          <el-table-column label="创建时间" min-width="190">
            <template #default="{ row }">{{ formatChinaTime(row.created_at) }}</template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="暂无研究资产" />
      </el-card>

      <div class="section-label-row">
        <span>最近回测</span>
        <small>最近运行和可继续分析的结果</small>
      </div>
      <el-card shadow="never" class="top-band">
        <el-table v-if="backtests.length" :data="backtests" size="default">
          <el-table-column label="回测编号" min-width="180"><template #default="{ row }">{{ shortReference(row.job_id) }}</template></el-table-column>
          <el-table-column label="状态" width="120"><template #default="{ row }">{{ statusLabel(row.status) }}</template></el-table-column>
          <el-table-column prop="created_at" label="创建时间" min-width="190" />
        </el-table>
        <el-empty v-else description="暂无回测任务" />
      </el-card>

      <div class="section-label-row">
        <span>服务健康</span>
        <small>只显示普通用户需要关注的可用状态</small>
      </div>
      <el-card shadow="never" class="top-band">
        <div class="status-list">
          <div><span>平台服务</span><strong>{{ health?.status === "ok" ? "正常" : "需检查" }}</strong></div>
          <div><span>研究模型</span><strong>{{ settings?.model_provider.configured ? "已配置" : "未配置" }}</strong></div>
          <div><span>审批待处理</span><strong>{{ settings?.approval_inbox.pending ?? 0 }}</strong></div>
          <div><span>研究过程记录</span><strong>{{ operations?.observability.workflow_trace ? "可用" : "-" }}</strong></div>
          <div><span>操作记录</span><strong>{{ operations?.observability.audit ? "可用" : "-" }}</strong></div>
        </div>
      </el-card>
    </template>
  </section>
</template>

<style scoped>
.resource-bars {
  display: grid;
  gap: 0.75rem;
}

.resource-bars > div {
  display: grid;
  gap: 0.25rem;
}

.resource-bars span {
  color: var(--byq-text-muted);
  font-size: 12px;
}
</style>
