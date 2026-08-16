<script setup lang="ts">
import { onMounted, ref } from "vue";
import { getSettingsStatus } from "@/api/settings";
import { listArtifacts } from "@/api/research";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const tab = ref<"profile" | "models" | "data" | "approvals" | "assets">("profile");
const loading = ref(true);
const error = ref("");
const status = ref<Awaited<ReturnType<typeof getSettingsStatus>> | null>(null);
const artifacts = ref<Array<Record<string, unknown>>>([]);

async function loadAssets() {
  try {
    artifacts.value = (await listArtifacts()).artifacts;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载资产失败";
  }
}

onMounted(async () => {
  try {
    status.value = await getSettingsStatus(auth.token);
    await loadAssets();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载失败";
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <section class="settings-page">
    <el-card shadow="never" class="top-band">
      <div v-if="loading" class="base-loading">加载中...</div>
      <div v-else-if="error" class="base-error">{{ error }}</div>
      <el-tabs v-else v-model="tab">
        <el-tab-pane label="个人设置" name="profile">
          <el-form label-position="top" class="settings-panel">
            <el-form-item label="当前账户">
              <el-input :model-value="auth.user?.subject ?? 'product-user'" disabled />
            </el-form-item>
            <el-form-item label="Profile 配置">
              <el-input :model-value="status?.profile.configured ? 'configured' : 'not_configured'" disabled />
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="个人模型" name="models">
          <el-form label-position="top" class="settings-panel">
            <el-form-item label="模型提供方">
              <el-input :model-value="status?.model_provider.configured ? 'configured' : 'not_configured'" disabled />
            </el-form-item>
            <el-form-item label="密钥状态">
              <el-input model-value="••••••••" disabled />
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="数据" name="data">
          <el-form label-position="top" class="settings-panel">
            <el-form-item label="Provider">
              <el-input :model-value="status?.data_provider.provider" disabled />
            </el-form-item>
            <el-form-item label="Migration">
              <el-input :model-value="status?.data_provider.migration" disabled />
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="审批偏好" name="approvals">
          <div class="status-list">
            <div><span>待处理审批</span><strong>{{ status?.approval_inbox.pending ?? 0 }}</strong></div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="用户资产" name="assets">
          <el-table :data="artifacts">
            <el-table-column prop="artifact_id" label="Artifact ID" min-width="260" show-overflow-tooltip />
            <el-table-column prop="kind" label="类型" width="150" />
            <el-table-column prop="status" label="状态" width="120" />
          </el-table>
          <el-empty v-if="!artifacts.length" description="暂无资产" />
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </section>
</template>
