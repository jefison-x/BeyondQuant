<script setup lang="ts">
import { onMounted, ref } from "vue";
import { getOperationsStatus } from "@/api/operations";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const loading = ref(true);
const error = ref("");
const status = ref<Awaited<ReturnType<typeof getOperationsStatus>> | null>(null);

onMounted(async () => {
  try {
    status.value = await getOperationsStatus(auth.token);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载失败";
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <section class="system-page">
    <div v-if="loading" class="base-loading">加载中...</div>
    <div v-else-if="error" class="base-error">{{ error }}</div>

    <template v-else>
      <div class="stats-strip">
        <div class="stat-item"><span>Backend</span><strong>{{ status?.services.backend }}</strong></div>
        <div class="stat-item"><span>Runtime</span><strong>{{ status?.runtime.runtime.status }}</strong></div>
        <div class="stat-item"><span>Storage</span><strong>{{ status?.database.status }}</strong></div>
        <div class="stat-item"><span>Migration</span><strong>{{ status?.database.migration.single_domain_store }}</strong></div>
      </div>

      <el-card shadow="never" class="top-band">
        <template #header>
          <div class="card-title">可观测性</div>
        </template>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="WorkflowTrace">
            {{ status?.observability.workflow_trace }}
          </el-descriptions-item>
          <el-descriptions-item label="Audit">
            {{ status?.observability.audit }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>
    </template>
  </section>
</template>
