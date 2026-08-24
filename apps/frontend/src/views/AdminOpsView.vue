<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { getOperationsStatus } from "@/api/operations";
import type { OperationsStatus } from "@/api/types";
import { useAuthStore } from "@/stores/auth";
import DatabaseOperations from "@/components/operations/DatabaseOperations.vue";
import SourceOperations from "@/components/operations/SourceOperations.vue";
import CacheOperations from "@/components/operations/CacheOperations.vue";
import ModelOperations from "@/components/operations/ModelOperations.vue";
import AgentOperations from "@/components/operations/AgentOperations.vue";
import BudgetOperations from "@/components/operations/BudgetOperations.vue";
import RuntimeOperations from "@/components/operations/RuntimeOperations.vue";
import GraphOperations from "@/components/operations/GraphOperations.vue";
import AccessOperations from "@/components/operations/AccessOperations.vue";

const props = defineProps<{ section: string }>();
const auth = useAuthStore();
const loading = ref(true);
const error = ref("");
const data = ref<OperationsStatus | null>(null);

const views: Record<string, unknown> = {
  database: DatabaseOperations,
  sources: SourceOperations,
  cache: CacheOperations,
  models: ModelOperations,
  agents: AgentOperations,
  budget: BudgetOperations,
  runtime: RuntimeOperations,
  graphs: GraphOperations,
  access: AccessOperations,
  audit: AccessOperations,
};
const activeView = computed(() => views[props.section] ?? DatabaseOperations);
const activeViewProps = computed(() => {
  if (props.section === "access") return { mode: "access" };
  if (props.section === "audit") return { mode: "audit" };
  return {};
});

async function load() {
  loading.value = true;
  error.value = "";
  try {
    data.value = await getOperationsStatus(auth.token);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "运维数据加载失败";
  } finally {
    loading.value = false;
  }
}

watch(() => props.section, load);
onMounted(load);
</script>

<template>
  <section class="system-page operations-page">
    <div class="operations-toolbar">
      <div>
        <el-tag effect="plain">管理员边界</el-tag>
        <span class="operations-boundary">Product API · 去敏投影 · 原始 DSH 事件不可见</span>
      </div>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </div>
    <div v-if="loading && !data" class="base-loading">正在读取真实运维投影...</div>
    <div v-else-if="error && !data" class="base-error">
      {{ error }}
      <el-button link type="primary" @click="load">重试</el-button>
    </div>
    <template v-else-if="data">
      <el-alert v-if="error" :title="error" type="warning" show-icon :closable="false" />
      <component :is="activeView" :data="data" v-bind="activeViewProps" @changed="load" />
    </template>
  </section>
</template>

<style scoped>
.operations-page { display: grid; gap: 16px; }
.operations-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.operations-boundary { margin-left: 10px; color: var(--byq-text-muted); font-size: 13px; }
@media (max-width: 720px) {
  .operations-toolbar { align-items: flex-start; }
  .operations-boundary { display: block; margin: 8px 0 0; }
}
</style>
