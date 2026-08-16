<script setup lang="ts">
import { onMounted, ref } from "vue";
import { fetchDataStatus, fetchHealth } from "@/api/client";
import { getDataCenterStatus } from "@/api/dataCenter";
import { getOperationsStatus } from "@/api/operations";
import { getSettingsStatus } from "@/api/settings";
import { listUsers } from "@/api/admin";
import { listApprovals } from "@/api/research";
import { useAuthStore } from "@/stores/auth";

const props = defineProps<{ section: string }>();
const auth = useAuthStore();
const loading = ref(true);
const error = ref("");
const operations = ref<Awaited<ReturnType<typeof getOperationsStatus>> | null>(null);
const dataStatus = ref<Awaited<ReturnType<typeof fetchDataStatus>> | null>(null);
const dataCenter = ref<Awaited<ReturnType<typeof getDataCenterStatus>> | null>(null);
const settings = ref<Awaited<ReturnType<typeof getSettingsStatus>> | null>(null);
const health = ref<Awaited<ReturnType<typeof fetchHealth>> | null>(null);
const users = ref<Array<Record<string, unknown>>>([]);
const approvals = ref<Array<Record<string, unknown>>>([]);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const results = await Promise.allSettled([
      getOperationsStatus(auth.token),
      fetchDataStatus(auth.token),
      getDataCenterStatus(),
      getSettingsStatus(auth.token),
      fetchHealth(auth.token),
      listUsers(),
      listApprovals(),
    ]);
    const [ops, data, center, settingsResult, healthResult, usersResult, approvalsResult] = results;
    if (ops.status === "fulfilled") operations.value = ops.value;
    if (data.status === "fulfilled") dataStatus.value = data.value;
    if (center.status === "fulfilled") dataCenter.value = center.value;
    if (settingsResult.status === "fulfilled") settings.value = settingsResult.value;
    if (healthResult.status === "fulfilled") health.value = healthResult.value;
    if (usersResult.status === "fulfilled") users.value = usersResult.value.users;
    if (approvalsResult.status === "fulfilled") approvals.value = approvalsResult.value.approvals;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section class="system-page">
    <div v-if="loading" class="base-loading">加载中...</div>
    <div v-else-if="error" class="base-error">{{ error }}</div>

    <template v-else>
      <div v-if="props.section === 'database'" class="ops-panel">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="Backend">{{ operations?.backend }}</el-descriptions-item>
          <el-descriptions-item label="Storage">{{ operations?.storage }}</el-descriptions-item>
          <el-descriptions-item label="Migration">{{ operations?.migration }}</el-descriptions-item>
        </el-descriptions>
      </div>

      <div v-else-if="props.section === 'sources'" class="ops-panel">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="Provider">{{ dataStatus?.provider }}</el-descriptions-item>
          <el-descriptions-item label="Migration">{{ dataStatus?.migration }}</el-descriptions-item>
        </el-descriptions>
      </div>

      <div v-else-if="props.section === 'cache'" class="ops-panel">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="质量状态">{{ dataCenter?.quality }}</el-descriptions-item>
          <el-descriptions-item label="数据集数量">{{ dataCenter?.datasets.length ?? 0 }}</el-descriptions-item>
        </el-descriptions>
      </div>

      <div v-else-if="props.section === 'models'" class="ops-panel">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="模型提供方">{{ settings?.model_provider.configured ? "configured" : "not_configured" }}</el-descriptions-item>
          <el-descriptions-item label="密钥状态">masked</el-descriptions-item>
        </el-descriptions>
      </div>

      <div v-else-if="props.section === 'agents'" class="ops-panel">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="Runtime">{{ operations?.runtime }}</el-descriptions-item>
          <el-descriptions-item label="WorkflowTrace">{{ operations?.observability.workflow_trace }}</el-descriptions-item>
        </el-descriptions>
      </div>

      <div v-else-if="props.section === 'budget'" class="ops-panel">
        <el-empty description="执行预算能力尚未接入 BYQ Product API" />
      </div>

      <div v-else-if="props.section === 'runtime'" class="ops-panel">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="Runtime">{{ operations?.runtime }}</el-descriptions-item>
          <el-descriptions-item label="Product Health">{{ health?.status }}</el-descriptions-item>
          <el-descriptions-item label="审计">{{ operations?.observability.audit }}</el-descriptions-item>
        </el-descriptions>
      </div>

      <div v-else-if="props.section === 'graphs'" class="ops-panel">
        <el-empty description="Graph 工作流能力尚未接入 BYQ Product API" />
      </div>

      <div v-else class="ops-panel">
        <div class="panel-heading">
          <div class="panel-title">用户</div>
          <el-tag>{{ users.length }}</el-tag>
        </div>
        <el-table :data="users">
          <el-table-column prop="username" label="用户名" min-width="160" />
          <el-table-column prop="role" label="角色" width="120" />
          <el-table-column prop="status" label="状态" width="120" />
        </el-table>
        <div class="panel-heading">
          <div class="panel-title">审批记录</div>
          <el-tag>{{ approvals.length }}</el-tag>
        </div>
        <el-table :data="approvals">
          <el-table-column prop="approval_id" label="Approval ID" min-width="240" show-overflow-tooltip />
          <el-table-column prop="action" label="动作" width="180" />
          <el-table-column prop="status" label="状态" width="120" />
        </el-table>
      </div>
    </template>
  </section>
</template>
