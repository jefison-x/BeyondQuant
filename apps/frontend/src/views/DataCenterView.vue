<script setup lang="ts">
import { onMounted, ref } from "vue";
import { getDataCenterStatus } from "@/api/dataCenter";
import BaseCard from "@/components/ui/BaseCard.vue";
import BaseEmpty from "@/components/ui/BaseEmpty.vue";
import BaseError from "@/components/ui/BaseError.vue";
import BaseLoading from "@/components/ui/BaseLoading.vue";

const loading = ref(true);
const error = ref("");
const status = ref<Awaited<ReturnType<typeof getDataCenterStatus>> | null>(null);

onMounted(async () => {
  try {
    status.value = await getDataCenterStatus();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载失败";
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <section class="page-card">
    <h2>Data Center</h2>
    <BaseLoading v-if="loading" />
    <BaseError v-else-if="error" :message="error" />
    <template v-else>
      <BaseCard title="迁移状态">
        <p>Migration: {{ status?.migration }}</p>
        <p>Provider: {{ status?.provider }}</p>
        <p>Quality: {{ status?.quality }}</p>
      </BaseCard>
      <BaseCard title="Datasets">
        <BaseEmpty v-if="!status?.datasets.length" message="暂无已迁移数据集" />
        <ul v-else>
          <li v-for="dataset in status?.datasets" :key="String(dataset.id)">{{ dataset }}</li>
        </ul>
      </BaseCard>
    </template>
  </section>
</template>
