<script setup lang="ts">
import { onMounted, ref } from "vue";
import { getSettingsStatus } from "@/api/settings";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const tab = ref<"profile" | "models" | "data" | "approvals" | "assets">("profile");
const loading = ref(true);
const error = ref("");
const status = ref<Awaited<ReturnType<typeof getSettingsStatus>> | null>(null);
const profile = ref({ nickname: "", default_prompt: "" });

onMounted(async () => {
  try {
    status.value = await getSettingsStatus(auth.token);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载失败";
  } finally {
    loading.value = false;
  }
});

function saveProfile() {
  // Phase 20 keeps profile local and secret-free; durable profile persistence
  // is deferred until the product user resource is implemented.
  localStorage.setItem("byq-profile", JSON.stringify(profile.value));
}
</script>

<template>
  <section class="page-card">
    <h2>用户与平台设置</h2>
    <div class="settings-tabs">
      <button type="button" :class="{ active: tab === 'profile' }" @click="tab = 'profile'">Profile</button>
      <button type="button" :class="{ active: tab === 'models' }" @click="tab = 'models'">Models</button>
      <button type="button" :class="{ active: tab === 'data' }" @click="tab = 'data'">Data</button>
      <button type="button" :class="{ active: tab === 'approvals' }" @click="tab = 'approvals'">Approvals</button>
      <button type="button" :class="{ active: tab === 'assets' }" @click="tab = 'assets'">Assets</button>
    </div>

    <p v-if="loading">加载中...</p>
    <p v-else-if="error" class="page-error">{{ error }}</p>

    <div v-else-if="tab === 'profile'" class="settings-panel">
      <label>昵称</label>
      <input v-model="profile.nickname" placeholder="昵称" />
      <label>默认研究提示词</label>
      <textarea v-model="profile.default_prompt" rows="3" placeholder="默认研究提示词" />
      <button type="button" @click="saveProfile">保存本地 Profile</button>
    </div>

    <div v-else-if="tab === 'models'" class="settings-panel">
      <p>Model provider configured: {{ status?.model_provider.configured ? "true" : "false" }}</p>
      <p>密钥字段仅显示掩码状态，浏览器不接收真实凭据。</p>
      <input value="••••••••" disabled />
    </div>

    <div v-else-if="tab === 'data'" class="settings-panel">
      <p>Provider: {{ status?.data_provider.provider }}</p>
      <p>Migration: {{ status?.data_provider.migration }}</p>
    </div>

    <div v-else-if="tab === 'approvals'" class="settings-panel">
      <p>Pending approvals: {{ status?.approval_inbox.pending }}</p>
    </div>

    <div v-else class="settings-panel">
      <p>Storage status: {{ status?.storage.status }}</p>
      <p>Artifacts 与资产索引将在后续 Product API 资源列表接入。</p>
    </div>
  </section>
</template>
