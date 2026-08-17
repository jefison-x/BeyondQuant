<script setup lang="ts">
import { onMounted, ref } from "vue";
import { getDataCenterStatus } from "@/api/dataCenter";

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
  <section class="data-sync-page">
    <div v-if="loading" class="base-loading">加载中...</div>
    <div v-else-if="error" class="base-error">{{ error }}</div>

    <template v-else>
      <div class="stats-strip">
        <div class="stat-item"><span>Provider</span><strong>{{ status?.provider }}</strong></div>
        <div class="stat-item"><span>Migration</span><strong>{{ status?.migration }}</strong></div>
        <div class="stat-item"><span>Quality</span><strong>{{ status?.quality }}</strong></div>
        <div class="stat-item"><span>数据源状态</span><strong>{{ status?.provider_status.configured ? "已配置" : "未配置" }}</strong></div>
        <div class="stat-item"><span>同步状态</span><strong>{{ status?.provider_status.sync }}</strong></div>
      </div>

      <el-card shadow="never" class="top-band">
        <template #header>
          <div class="card-title">已迁移数据集</div>
        </template>
        <el-empty v-if="!status?.datasets.length" description="暂无已迁移数据集" />
        <el-table v-else :data="status?.datasets">
          <el-table-column prop="id" label="ID" min-width="180" show-overflow-tooltip />
          <el-table-column prop="name" label="名称" min-width="180" />
          <el-table-column prop="status" label="状态" width="140" />
        </el-table>
      </el-card>
    </template>
  </section>
</template>
