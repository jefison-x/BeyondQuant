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
  <section class="page-card">
    <h2>Operations 状态</h2>
    <p v-if="loading">加载中...</p>
    <p v-else-if="error" class="page-error">{{ error }}</p>
    <dl v-else class="status-list">
      <div><dt>Backend</dt><dd>{{ status?.backend }}</dd></div>
      <div><dt>Runtime</dt><dd>{{ status?.runtime }}</dd></div>
      <div><dt>Storage</dt><dd>{{ status?.storage }}</dd></div>
      <div><dt>Migration</dt><dd>{{ status?.migration }}</dd></div>
      <div><dt>WorkflowTrace</dt><dd>{{ status?.observability.workflow_trace }}</dd></div>
      <div><dt>Audit</dt><dd>{{ status?.observability.audit }}</dd></div>
    </dl>
  </section>
</template>
