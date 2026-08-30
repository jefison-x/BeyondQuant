<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  createModelCredential, createModelProfile, deleteModelProfile, getModelSettings,
  revokeModelCredential, updateModelBinding, updateModelCredential,
} from "@/api/settings";
import type { ModelCredential, ModelProfile, ModelSettings } from "@/api/types";

const loading = ref(true);
const busy = ref(false);
const error = ref("");
const settings = ref<ModelSettings | null>(null);
const credentialDialog = ref(false);
const profileDialog = ref(false);
const editingCredential = ref<ModelCredential | null>(null);
const credentialForm = reactive({ provider: "deepseek", label: "", secret: "" });
const profileForm = reactive({ credential_id: "", key_name: "", display_name: "", provider: "deepseek", model: "deepseek-v4-flash", temperature: 0.2, reasoning_enabled: false });

const activeCredentials = computed(() => (settings.value?.credential_items ?? []).filter((item) => item.status === "active"));
const modelsForProvider = computed(() => (settings.value?.models ?? []).filter((item) => item.provider === profileForm.provider));
const availableProfiles = computed(() => (settings.value?.profiles ?? []).filter((item) => item.available));
const selectedModel = computed(() => settings.value?.models.find((item) => item.provider === profileForm.provider && item.model === profileForm.model));
const selectedProvider = computed(() => settings.value?.providers.find((item) => item.provider === credentialForm.provider));

function providerName(provider: string) {
  return settings.value?.providers.find((item) => item.provider === provider)?.display_name ?? provider;
}

function selectCredentialProvider(provider: string) {
  if (!editingCredential.value) credentialForm.label = `个人 ${providerName(provider)} API`;
}

async function load() {
  loading.value = true;
  error.value = "";
  try { settings.value = await getModelSettings(); }
  catch (exc) { error.value = exc instanceof Error ? exc.message : "加载个人模型失败"; }
  finally { loading.value = false; }
}

onMounted(load);

function openCredential(item: ModelCredential | null = null) {
  editingCredential.value = item;
  credentialForm.provider = item?.provider ?? settings.value?.providers[0]?.provider ?? "deepseek";
  credentialForm.label = item?.label ?? `个人 ${providerName(credentialForm.provider)} API`;
  credentialForm.secret = "";
  credentialDialog.value = true;
}

async function saveCredential() {
  if (!credentialForm.label.trim() || !credentialForm.secret.trim()) return ElMessage.warning("请输入名称和 API Key");
  busy.value = true;
  try {
    if (editingCredential.value) {
      await updateModelCredential(editingCredential.value.credential_id, {
        label: credentialForm.label, secret: credentialForm.secret,
        expected_version: editingCredential.value.version, request_id: `browser-replace-${Date.now()}`,
      });
      ElMessage.success("凭据已安全替换");
    } else {
      await createModelCredential({ purpose: "model_api_key", provider: credentialForm.provider, scope: "user", label: credentialForm.label, secret: credentialForm.secret, idempotency_key: `browser-create-${Date.now()}` });
      ElMessage.success("凭据已保存");
    }
    credentialDialog.value = false;
    credentialForm.secret = "";
    await load();
  } catch (exc) { ElMessage.error(exc instanceof Error ? exc.message : "保存凭据失败"); }
  finally { busy.value = false; }
}

async function setCredentialStatus(item: ModelCredential, status: "active" | "disabled") {
  busy.value = true;
  try {
    await updateModelCredential(item.credential_id, { label: item.label, status, expected_version: item.version, request_id: `browser-status-${Date.now()}` });
    await load();
  } catch (exc) { ElMessage.error(exc instanceof Error ? exc.message : "更新凭据失败"); }
  finally { busy.value = false; }
}

async function revoke(item: ModelCredential) {
  try {
    await ElMessageBox.confirm("撤销后密文会被清除，使用它的档案将立即不可用。", "撤销凭据", { type: "warning", confirmButtonText: "确认撤销" });
    await revokeModelCredential(item.credential_id, { expected_version: item.version, request_id: `browser-revoke-${Date.now()}` });
    ElMessage.success("凭据已撤销");
    await load();
  } catch (exc) { if (exc !== "cancel" && exc !== "close") ElMessage.error(exc instanceof Error ? exc.message : "撤销失败"); }
}

function openProfile() {
  const credential = activeCredentials.value[0];
  profileForm.provider = credential?.provider ?? settings.value?.providers[0]?.provider ?? "deepseek";
  profileForm.credential_id = credential?.credential_id ?? "";
  profileForm.key_name = "";
  profileForm.display_name = "";
  profileForm.model = modelsForProvider.value[0]?.model ?? "deepseek-v4-flash";
  profileForm.temperature = 0.2;
  profileForm.reasoning_enabled = false;
  profileDialog.value = true;
}

async function saveProfile() {
  if (!profileForm.credential_id || !profileForm.key_name.trim() || !profileForm.display_name.trim()) return ElMessage.warning("请完整填写模型档案");
  busy.value = true;
  try {
    await createModelProfile({ ...profileForm });
    profileDialog.value = false;
    ElMessage.success("模型档案已创建");
    await load();
  } catch (exc) { ElMessage.error(exc instanceof Error ? exc.message : "创建档案失败"); }
  finally { busy.value = false; }
}

watch(() => profileForm.credential_id, credentialId => {
  const credential = activeCredentials.value.find((item) => item.credential_id === credentialId);
  if (!credential) return;
  profileForm.provider = credential.provider;
  if (!modelsForProvider.value.some((item) => item.model === profileForm.model)) {
    profileForm.model = modelsForProvider.value[0]?.model ?? "";
    profileForm.reasoning_enabled = false;
  }
});

async function removeProfile(item: ModelProfile) {
  try {
    await ElMessageBox.confirm("删除档案会将关联 Agent 恢复为系统默认。", "删除模型档案", { type: "warning" });
    await deleteModelProfile(item.profile_id, item.version);
    await load();
  } catch (exc) { if (exc !== "cancel" && exc !== "close") ElMessage.error(exc instanceof Error ? exc.message : "删除失败"); }
}

async function bind(agentId: string, profileId: string | null, version: number) {
  busy.value = true;
  try {
    await updateModelBinding(agentId, profileId || null, version);
    ElMessage.success(profileId ? "Agent 模型绑定已更新" : "已恢复系统默认");
    await load();
  } catch (exc) { ElMessage.error(exc instanceof Error ? exc.message : "绑定失败"); }
  finally { busy.value = false; }
}

function actionLabel(value: unknown) {
  return ({ created: "创建", secret_replaced: "替换密钥", enabled: "启用", disabled: "停用", revoked: "撤销" } as Record<string, string>)[String(value)] ?? String(value ?? "-");
}
</script>

<template>
  <section class="my-space-page">
    <el-alert title="密钥仅可写入，不会返回浏览器、日志或 WorkflowTrace；运行时通过 Backend 私有边界按当前用户解析。" type="info" show-icon :closable="false" />
    <div v-if="loading" class="base-loading" role="status" aria-live="polite">加载中...</div>
    <div v-else-if="error" class="base-error" role="alert">{{ error }}</div>
    <template v-else>
      <el-card shadow="never">
        <template #header><div class="card-header"><div><strong>模型凭据</strong><p class="muted">AES-256-GCM 信封加密 · {{ settings?.encryption.configured ? "密钥环就绪" : "加密不可用" }}</p></div><el-button type="primary" :disabled="!settings?.encryption.configured" @click="openCredential()">添加凭据</el-button></div></template>
        <el-table :data="settings?.credential_items ?? []" empty-text="尚未配置凭据">
          <el-table-column prop="label" label="名称" min-width="150" />
          <el-table-column label="厂商" min-width="130"><template #default="scope">{{ providerName(scope.row.provider) }}</template></el-table-column>
          <el-table-column prop="masked" label="掩码" min-width="130" />
          <el-table-column label="状态" width="100"><template #default="scope"><el-tag :type="scope.row.status === 'active' ? 'success' : scope.row.status === 'revoked' ? 'danger' : 'info'">{{ scope.row.status }}</el-tag></template></el-table-column>
          <el-table-column label="操作" min-width="260"><template #default="scope"><el-button link type="primary" :disabled="scope.row.status === 'revoked'" @click="openCredential(scope.row)">替换</el-button><el-button v-if="scope.row.status === 'active'" link @click="setCredentialStatus(scope.row, 'disabled')">停用</el-button><el-button v-else-if="scope.row.status === 'disabled'" link @click="setCredentialStatus(scope.row, 'active')">启用</el-button><el-button link type="danger" :disabled="scope.row.status === 'revoked'" @click="revoke(scope.row)">撤销</el-button></template></el-table-column>
        </el-table>
      </el-card>

      <el-card shadow="never">
        <template #header><div class="card-header"><div><strong>模型档案</strong><p class="muted">模型参数与凭据分离，可复用于 Agent 绑定。</p></div><el-button type="primary" :disabled="!activeCredentials.length" @click="openProfile">新建档案</el-button></div></template>
        <el-table :data="settings?.profiles ?? []" empty-text="尚无模型档案">
          <el-table-column prop="display_name" label="档案" min-width="150" />
          <el-table-column label="厂商" min-width="130"><template #default="scope">{{ providerName(scope.row.provider) }}</template></el-table-column>
          <el-table-column prop="model" label="模型" min-width="170" />
          <el-table-column prop="temperature" label="温度" width="80" />
          <el-table-column label="可用" width="90"><template #default="scope"><el-tag :type="scope.row.available ? 'success' : 'danger'">{{ scope.row.available ? "可用" : "不可用" }}</el-tag></template></el-table-column>
          <el-table-column label="操作" width="100"><template #default="scope"><el-button link type="danger" :disabled="scope.row.status === 'deleted'" @click="removeProfile(scope.row)">删除</el-button></template></el-table-column>
        </el-table>
      </el-card>

      <el-card shadow="never">
        <template #header><div><strong>Agent 绑定</strong><p class="muted">显式选择个人档案；未绑定时使用服务端系统默认。</p></div></template>
        <div v-for="binding in settings?.bindings" :key="binding.agent_id" class="binding-row">
          <div><strong>{{ binding.agent_name }}</strong><p class="muted">{{ binding.effective_source === "personal" ? `个人档案 · ${binding.model}` : "系统默认" }}</p></div>
          <el-select :model-value="binding.profile_id ?? ''" :aria-label="`${binding.agent_name} 模型档案`" :disabled="busy" @change="bind(binding.agent_id, String($event) || null, binding.version)"><el-option label="系统默认" value="" /><el-option v-for="profile in availableProfiles" :key="profile.profile_id" :label="`${profile.display_name} · ${profile.model}`" :value="profile.profile_id" /></el-select>
        </div>
      </el-card>

      <el-card shadow="never">
        <template #header><div><strong>凭据审计</strong><p class="muted">仅记录元数据，不记录密钥明文或密文。</p></div></template>
        <el-table :data="settings?.audit ?? []" size="small" empty-text="暂无审计记录"><el-table-column label="动作" width="120"><template #default="scope">{{ actionLabel(scope.row.action) }}</template></el-table-column><el-table-column prop="credential_id" label="凭据" min-width="230" show-overflow-tooltip /><el-table-column prop="created_at" label="时间" min-width="180" /></el-table>
      </el-card>
    </template>

    <el-dialog v-model="credentialDialog" :title="editingCredential ? '替换模型凭据' : '添加模型凭据'" width="min(520px, 92vw)" destroy-on-close>
      <el-form label-position="top"><el-form-item label="模型厂商"><el-select v-model="credentialForm.provider" class="full" :disabled="Boolean(editingCredential)" @change="selectCredentialProvider"><el-option v-for="item in settings?.providers" :key="item.provider" :label="item.display_name" :value="item.provider" /></el-select></el-form-item><el-form-item label="名称"><el-input v-model="credentialForm.label" maxlength="120" /></el-form-item><el-form-item :label="selectedProvider?.credential_label ?? 'API Key'"><el-input v-model="credentialForm.secret" type="password" show-password autocomplete="new-password" placeholder="写入后仅显示掩码" /></el-form-item></el-form>
      <template #footer><el-button @click="credentialDialog = false">取消</el-button><el-button type="primary" :loading="busy" @click="saveCredential">安全保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="profileDialog" title="新建模型档案" width="min(560px, 92vw)" destroy-on-close>
      <el-form label-position="top"><el-form-item label="档案名称"><el-input v-model="profileForm.display_name" /></el-form-item><el-form-item label="唯一键"><el-input v-model="profileForm.key_name" placeholder="research-fast" /></el-form-item><el-form-item label="凭据"><el-select v-model="profileForm.credential_id" class="full"><el-option v-for="item in activeCredentials" :key="item.credential_id" :label="`${providerName(item.provider)} · ${item.label} · ${item.masked}`" :value="item.credential_id" /></el-select></el-form-item><el-form-item label="模型"><el-select v-model="profileForm.model" class="full"><el-option v-for="model in modelsForProvider" :key="`${model.provider}:${model.model}`" :label="model.display_name" :value="model.model" /></el-select></el-form-item><el-form-item label="温度"><el-slider v-model="profileForm.temperature" :min="0" :max="2" :step="0.1" show-input /></el-form-item><el-form-item label="推理模式"><el-switch v-model="profileForm.reasoning_enabled" :disabled="!selectedModel?.reasoning_supported" /></el-form-item></el-form>
      <template #footer><el-button @click="profileDialog = false">取消</el-button><el-button type="primary" :loading="busy" @click="saveProfile">创建档案</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.my-space-page { display: grid; gap: 1rem; min-width: 0; }
.card-header, .binding-row { align-items: center; display: flex; gap: 1rem; justify-content: space-between; }
.binding-row { border-bottom: 1px solid var(--byq-border); padding: .75rem 0; }
.binding-row:last-child { border-bottom: 0; }
.binding-row .el-select { min-width: 280px; }
.muted { color: var(--byq-text-muted); font-size: 12px; margin: .3rem 0 0; }
.full { width: 100%; }
@media (max-width: 640px) { .card-header, .binding-row { align-items: flex-start; flex-direction: column; } .binding-row .el-select { min-width: 0; width: 100%; } }
</style>
