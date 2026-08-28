<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { getProfile, updateProfile } from "@/api/settings";
import type { UserProfile } from "@/api/types";
import { useUnsavedChanges } from "@/composables/useUnsavedChanges";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const loading = ref(true);
const saving = ref(false);
const error = ref("");
const profile = ref<UserProfile | null>(null);
const form = ref({ display_name: "", preferences: "", default_prompt: "" });
const savedForm = ref("");
const dirty = computed(() => !loading.value && JSON.stringify(form.value) !== savedForm.value);
useUnsavedChanges(dirty);

onMounted(async () => {
  try {
    const body = await getProfile();
    profile.value = body.profile;
    form.value = {
      display_name: body.profile.display_name ?? "",
      preferences: body.profile.preferences ?? "",
      default_prompt: body.profile.default_prompt ?? "",
    };
    savedForm.value = JSON.stringify(form.value);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载个人设置失败";
  } finally {
    loading.value = false;
  }
});

async function save() {
  saving.value = true;
  try {
    const body = await updateProfile(form.value);
    profile.value = body.profile;
    form.value = {
      display_name: body.profile.display_name ?? "",
      preferences: body.profile.preferences ?? "",
      default_prompt: body.profile.default_prompt ?? "",
    };
    savedForm.value = JSON.stringify(form.value);
    if (auth.user) {
      auth.setUser({ ...auth.user, display_name: body.profile.display_name ?? "" });
    }
    ElMessage.success("个人设置已保存");
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "保存个人设置失败");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <section class="my-space-page">
    <el-alert
      title="个人资料会带入小巴投研对话：对话中会使用你的昵称，小巴会遵循你的偏好和默认提示词。"
      type="info"
      show-icon
      :closable="false"
    />

    <el-card shadow="never">
      <template #header>
        <div class="page-card-heading">
          <div>
            <div class="page-card-title">个人设置</div>
            <div class="page-card-sub">昵称、研究偏好与默认提示词</div>
          </div>
        </div>
      </template>

      <div v-if="loading" class="base-loading" role="status" aria-live="polite">加载中...</div>
      <div v-else-if="error" class="base-error" role="alert">{{ error }}</div>
      <el-form v-else label-position="top" class="profile-form">
        <el-form-item label="昵称">
          <el-input v-model="form.display_name" maxlength="80" show-word-limit placeholder="例如：老李 / 量化小周" />
          <div class="form-hint">对话中的用户消息会显示该昵称；未设置时显示“我”。</div>
        </el-form-item>
        <el-form-item label="偏好">
          <el-input
            v-model="form.preferences"
            type="textarea"
            :rows="4"
            maxlength="2000"
            show-word-limit
            placeholder="例如：偏好低波动高股息标的；分析时先给结论再给依据；回测优先使用 Native 引擎。"
          />
        </el-form-item>
        <el-form-item label="默认提示词">
          <el-input
            v-model="form.default_prompt"
            type="textarea"
            :rows="4"
            maxlength="2000"
            show-word-limit
            placeholder="例如：每次回答先用一句话说明结论，再展开依据；遇到数据缺失要明确说明，不要猜测。"
          />
          <div class="form-hint">小巴每次回答都会先遵循该提示词。</div>
        </el-form-item>
        <div class="form-actions">
          <span class="save-state" aria-live="polite">{{ dirty ? "有未保存更改" : "已保存" }}</span>
          <el-button type="primary" :loading="saving" :disabled="!dirty" @click="save">保存设置</el-button>
        </div>
      </el-form>
    </el-card>
  </section>
</template>

<style scoped>
.my-space-page {
  display: grid;
  gap: 1rem;
  min-width: 0;
}

.page-card-heading {
  align-items: center;
  display: flex;
  gap: 1rem;
  justify-content: space-between;
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

.profile-form {
  max-width: 720px;
}

.form-hint {
  color: var(--byq-text-muted);
  font-size: 12px;
  line-height: 1.5;
  margin-top: 0.35rem;
}

.form-actions {
  align-items: center;
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}

.save-state { color: var(--byq-text-muted); font-size: 12px; }
</style>
