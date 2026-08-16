<script setup lang="ts">
import { onMounted, ref } from "vue";
import { getModelSettings } from "@/api/settings";
import type { ModelSettings } from "@/api/types";

const loading = ref(true);
const error = ref("");
const settings = ref<ModelSettings | null>(null);

onMounted(async () => {
  try {
    settings.value = await getModelSettings();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载个人模型失败";
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <section class="my-space-page">
    <el-alert
      title="个人模型凭据与 Agent 绑定只属于当前用户；未配置时仅 Agent 辅助能力降级，策略、股票池和回测仍可继续使用。"
      type="info"
      show-icon
      :closable="false"
    />

    <el-card shadow="never">
      <template #header>
        <div>
          <div class="page-card-title">个人模型</div>
          <div class="page-card-sub">凭据状态与可用模型档案</div>
        </div>
      </template>

      <div v-if="loading" class="base-loading">加载中...</div>
      <div v-else-if="error" class="base-error">{{ error }}</div>
      <el-descriptions v-else :column="1" border>
        <el-descriptions-item label="模型提供方">{{ settings?.provider }}</el-descriptions-item>
        <el-descriptions-item label="凭据状态">
          <el-tag :type="settings?.configured ? 'success' : 'info'">
            {{ settings?.configured ? "已配置" : "未配置" }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="密钥展示">{{ settings?.credentials.masked ? "已掩码，仅可写入" : "-" }}</el-descriptions-item>
        <el-descriptions-item label="可用模型">
          <el-empty v-if="!settings?.models.length" description="暂无可用模型" :image-size="60" />
          <el-tag v-for="model in settings?.models" v-else :key="String(model.id ?? model.name)" class="model-tag">
            {{ model.name ?? model.id }}
          </el-tag>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>
  </section>
</template>

<style scoped>
.my-space-page {
  display: grid;
  gap: 1rem;
  min-width: 0;
}

.page-card-title {
  font-size: 16px;
  font-weight: 700;
}

.page-card-sub {
  color: var(--byq-text-muted);
  font-size: 12px;
  margin-top: 0.3rem;
}

.model-tag {
  margin-right: 0.4rem;
}
</style>
