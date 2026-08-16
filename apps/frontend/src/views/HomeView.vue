<script setup lang="ts">
import { onMounted, ref } from "vue";
import { fetchDashboard, ProductApiError } from "@/api/client";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const loading = ref(true);
const error = ref("");
const dashboard = ref<Awaited<ReturnType<typeof fetchDashboard>> | null>(null);

onMounted(async () => {
  try {
    dashboard.value = await fetchDashboard(auth.token);
  } catch (exc) {
    error.value = exc instanceof ProductApiError ? exc.message : "加载失败";
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <section class="page-card">
    <h2>首页</h2>
    <p v-if="loading">加载中...</p>
    <p v-else-if="error" class="page-error">{{ error }}</p>
    <div v-else class="resource-grid">
      <div v-for="(value, key) in dashboard?.resources" :key="key" class="resource-card">
        <strong>{{ key }}</strong>
        <span>{{ value }}</span>
      </div>
    </div>
  </section>
</template>
