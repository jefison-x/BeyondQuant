<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { fetchDataStatus } from "@/api/client";
import { getOperationsStatus } from "@/api/operations";
import type { OperationsStatus } from "@/api/types";

const route = useRoute();
const router = useRouter();
const loading = ref(true);
const error = ref("");
const operations = ref<OperationsStatus | null>(null);
const dataStatus = ref<Awaited<ReturnType<typeof fetchDataStatus>> | null>(null);

const readyServices = computed(() => {
  const services = operations.value?.services ?? {};
  return Object.values(services).filter((value) => value === "ready" || value === "ok").length;
});

async function load() {
  loading.value = true;
  error.value = "";
  try {
    [operations.value, dataStatus.value] = await Promise.all([
      getOperationsStatus(""),
      fetchDataStatus(""),
    ]);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "系统概览加载失败";
  } finally {
    loading.value = false;
  }
}

function open(path: string) {
  void router.push({ path, query: route.query });
}

onMounted(load);
</script>

<template>
  <section class="system-overview">
    <div class="overview-toolbar">
      <el-alert title="这里只显示有界、去敏的 Product API 状态；不提供数据库切换、任意 SQL、原始 DSH 事件或部署控制。" type="info" show-icon :closable="false" />
      <el-button :loading="loading" @click="load">刷新全部</el-button>
    </div>
    <div v-if="loading && !operations" class="base-loading">正在读取系统概览...</div>
    <div v-else-if="error && !operations" class="base-error">{{ error }} <el-button link type="primary" @click="load">重试</el-button></div>
    <template v-else-if="operations">
      <el-alert v-if="error" :title="error" type="warning" show-icon :closable="false" />
      <div class="ops-metrics">
        <el-card shadow="never"><span>核心服务</span><strong>{{ readyServices }}</strong><small>已就绪投影</small></el-card>
        <el-card shadow="never"><span>PostgreSQL</span><strong>{{ operations.database.status }}</strong><small>{{ operations.database.server_version }}</small></el-card>
        <el-card shadow="never"><span>行情缓存</span><strong>{{ operations.cache.row_count.toLocaleString() }}</strong><small>{{ operations.cache.kind }}</small></el-card>
        <el-card shadow="never"><span>DSH Runtime</span><strong>{{ operations.runtime.runtime.status }}</strong><small>规范化运行边界</small></el-card>
      </div>
      <div class="overview-grid">
        <el-card shadow="never">
          <template #header><strong>数据与存储</strong></template>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="Provider">{{ dataStatus?.provider ?? operations.sources.provider }}</el-descriptions-item>
            <el-descriptions-item label="迁移">{{ dataStatus?.migration ?? "-" }}</el-descriptions-item>
            <el-descriptions-item label="数据库">{{ operations.database.name }}</el-descriptions-item>
            <el-descriptions-item label="Redis">{{ operations.cache.redis }}</el-descriptions-item>
          </el-descriptions>
          <div class="card-actions"><el-button @click="open('/settings/system/data')">打开数据管理</el-button><el-button @click="open('/settings/system/database')">查看数据库</el-button></div>
        </el-card>
        <el-card shadow="never">
          <template #header><strong>Agent 与治理</strong></template>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="模型档案">{{ operations.models.profiles }}</el-descriptions-item>
            <el-descriptions-item label="模型绑定">{{ operations.models.bindings }}</el-descriptions-item>
            <el-descriptions-item label="WorkflowTrace">{{ operations.observability.workflow_trace }}</el-descriptions-item>
            <el-descriptions-item label="审计">{{ operations.observability.audit }}</el-descriptions-item>
          </el-descriptions>
          <div class="card-actions"><el-button @click="open('/settings/system/runtime')">查看运行时</el-button><el-button @click="open('/settings/system/audit')">查看审计</el-button></div>
        </el-card>
      </div>
    </template>
  </section>
</template>

<style scoped>
.system-overview { display: grid; gap: 16px; }
.overview-toolbar { align-items: flex-start; display: grid; gap: 12px; grid-template-columns: minmax(0, 1fr) auto; }
.overview-grid { display: grid; gap: 14px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.card-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
@media (max-width: 900px) { .overview-grid { grid-template-columns: 1fr; } }
@media (max-width: 620px) { .overview-toolbar { grid-template-columns: 1fr; } .overview-toolbar .el-button { width: 100%; } }
</style>
