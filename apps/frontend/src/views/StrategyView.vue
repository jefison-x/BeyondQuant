<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { getResearchEntity, exportStrategyVersion, listStrategies } from "@/api/quant";
import { useAuthStore } from "@/stores/auth";
import { formatChinaTime } from "@/time";

const auth = useAuthStore();
const loading = ref(true);
const error = ref("");
const busy = ref(false);
const artifacts = ref<Array<Record<string, unknown>>>([]);
const selected = ref<Record<string, unknown> | null>(null);
const detail = ref<Record<string, unknown> | null>(null);

const strategies = computed(() => artifacts.value.filter((artifact) => artifact.kind === "strategy_version"));

async function loadList() {
  loading.value = true;
  error.value = "";
  try {
    const response = await listStrategies(auth.token);
    artifacts.value = response.strategies;
    if (strategies.value.length) {
      await select(strategies.value[0]);
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

async function select(row: Record<string, unknown>) {
  selected.value = row;
  detail.value = null;
  error.value = "";
  try {
    const id = String(row.artifact_id);
    detail.value = await getResearchEntity("artifacts", id, auth.token);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "读取失败";
  }
}

async function exportVersion() {
  if (!selected.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await exportStrategyVersion(String(selected.value.artifact_id), auth.token);
    detail.value = result as Record<string, unknown>;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "导出失败";
  } finally {
    busy.value = false;
  }
}

onMounted(loadList);
</script>

<template>
  <section class="strategy-page">
    <div v-if="loading" class="base-loading">加载中...</div>
    <div v-else-if="error && !selected" class="base-error">{{ error }}</div>

    <div v-else class="strategy-workbench">
      <el-card shadow="never" class="strategy-list-pane">
        <template #header>
          <div class="card-heading">
            <span class="card-title">策略版本</span>
            <small class="card-sub">Artifact kind: strategy_version</small>
          </div>
        </template>
        <el-empty v-if="!strategies.length" description="暂无策略版本" />
        <el-table
          v-else
          :data="strategies"
          highlight-current-row
          @current-change="select"
        >
          <el-table-column prop="artifact_id" label="Artifact ID" min-width="220" show-overflow-tooltip />
          <el-table-column prop="status" label="状态" width="110" />
          <el-table-column label="创建时间" min-width="180">
            <template #default="{ row }">{{ formatChinaTime(row.created_at) }}</template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card shadow="never" class="strategy-detail-pane">
        <template #header>
          <div class="panel-heading">
            <div>
              <div class="panel-title">策略详情</div>
              <div class="panel-sub">{{ selected?.artifact_id ?? "未选择策略" }}</div>
            </div>
            <el-button type="primary" :loading="busy" :disabled="!selected" @click="exportVersion">
              导出版本
            </el-button>
          </div>
        </template>
        <p v-if="error" class="page-error">{{ error }}</p>
        <el-empty v-else-if="!detail" description="请选择左侧策略版本" />
        <pre v-else class="quant-result">{{ JSON.stringify(detail, null, 2) }}</pre>
      </el-card>
    </div>
  </section>
</template>

<style scoped>
.strategy-workbench {
  display: grid;
  grid-template-columns: minmax(340px, 0.9fr) minmax(0, 1.1fr);
  gap: 1rem;
}

@media (max-width: 900px) {
  .strategy-workbench {
    grid-template-columns: 1fr;
  }
}
</style>
