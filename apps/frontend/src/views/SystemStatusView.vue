<script setup lang="ts">
import { onMounted, ref } from "vue";
import { fetchDataStatus } from "@/api/client";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const loading = ref(true);
const error = ref("");
const status = ref<Awaited<ReturnType<typeof fetchDataStatus>> | null>(null);

onMounted(async () => {
  try {
    status.value = await fetchDataStatus(auth.token);
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

    <div v-else class="stats-strip">
      <div class="stat-item"><span>Provider</span><strong>{{ status?.provider }}</strong></div>
      <div class="stat-item"><span>Migration</span><strong>{{ status?.migration }}</strong></div>
      <div class="stat-item"><span>Backend</span><strong>{{ status?.backend }}</strong></div>
    </div>
  </section>
</template>
