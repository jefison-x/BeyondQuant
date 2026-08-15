<script setup lang="ts">
import { onMounted, ref } from "vue";
import { fetchDataStatus, ProductApiError } from "@/api/client";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const loading = ref(true);
const error = ref("");
const status = ref<Awaited<ReturnType<typeof fetchDataStatus>> | null>(null);

onMounted(async () => {
  try {
    status.value = await fetchDataStatus(auth.token);
  } catch (exc) {
    error.value = exc instanceof ProductApiError ? exc.message : "加载失败";
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <section class="page-card">
    <h2>系统状态</h2>
    <p v-if="loading">加载中...</p>
    <p v-else-if="error" class="page-error">{{ error }}</p>
    <dl v-else class="status-list">
      <div><dt>Provider</dt><dd>{{ status?.provider }}</dd></div>
      <div><dt>Migration</dt><dd>{{ status?.migration }}</dd></div>
      <div><dt>Backend</dt><dd>{{ status?.backend }}</dd></div>
    </dl>
  </section>
</template>
