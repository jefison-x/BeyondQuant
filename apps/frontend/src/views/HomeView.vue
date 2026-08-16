<script setup lang="ts">
import { onMounted, ref } from "vue";
import { fetchDashboard, ProductApiError } from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import BaseCard from "@/components/ui/BaseCard.vue";
import BaseBadge from "@/components/ui/BaseBadge.vue";
import BaseEmpty from "@/components/ui/BaseEmpty.vue";
import BaseError from "@/components/ui/BaseError.vue";
import BaseLoading from "@/components/ui/BaseLoading.vue";

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
  <section class="dashboard">
    <BaseLoading v-if="loading" />
    <BaseError v-else-if="error" :message="error" />
    <template v-else>
      <BaseCard title="系统状态">
        <div class="resource-grid">
          <div v-for="(value, key) in dashboard?.resources" :key="key" class="resource-card">
            <strong>{{ key }}</strong>
            <BaseBadge :label="value" :tone="value === 'ok' ? 'success' : 'warning'" />
          </div>
        </div>
      </BaseCard>
      <BaseCard title="最近研究">
        <BaseEmpty message="暂无研究记录" />
      </BaseCard>
      <BaseCard title="待处理审批">
        <BaseEmpty message="暂无待处理审批" />
      </BaseCard>
    </template>
  </section>
</template>
