<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Bell, CaretBottom, FolderOpened, SetUp, SwitchButton, Tools, User } from "@element-plus/icons-vue";
import { useAuthStore } from "@/stores/auth";

const props = withDefaults(
  defineProps<{
    variant?: "sidebar" | "mobile";
    mobileLabel?: string;
    compact?: boolean;
  }>(),
  {
    variant: "sidebar",
    mobileLabel: "我的",
  },
);
const emit = defineEmits<{ (event: "navigate"): void }>();

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

const displayName = computed(() => auth.user?.subject ?? "未登录");
const workspaceName = computed(() => auth.user?.workspace?.display_name ?? "个人工作区");
const avatarText = computed(() => displayName.value.slice(0, 1).toUpperCase() || "B");

async function handleCommand(command: string) {
  if (command === "logout") {
    await auth.logout();
    await router.push({ name: "login" });
    return;
  }
  if (command === "system-settings") {
    emit("navigate");
    await router.push({ path: "/settings/system/overview", query: { returnTo: route.fullPath } });
    return;
  }
  emit("navigate");
  await router.push(command);
}
</script>

<template>
  <div class="user-settings-menu" :class="`is-${props.variant}`">
    <el-dropdown trigger="click" placement="top-start" @command="handleCommand">
      <button type="button" class="user-trigger" :title="`用户设置：${displayName}`">
        <span class="user-avatar">{{ avatarText }}</span>
        <span v-if="props.variant === 'mobile' && props.mobileLabel" class="mobile-label">
          {{ props.mobileLabel }}
        </span>
        <span v-else-if="!props.compact" class="user-copy">
          <strong>{{ displayName }}</strong>
          <small>{{ workspaceName }}</small>
        </span>
        <el-icon v-if="props.variant !== 'mobile' && !props.compact" class="user-caret"><CaretBottom /></el-icon>
      </button>
      <template #dropdown>
        <el-dropdown-menu>
          <li v-if="auth.user" class="workspace-orientation" aria-label="当前个人工作区">
            <span>当前个人工作区</span>
            <strong>{{ workspaceName }}</strong>
            <small>仅你本人可访问 · 无需切换</small>
          </li>
          <el-dropdown-item command="/user/appearance"><el-icon><User /></el-icon>个性化</el-dropdown-item>
          <el-dropdown-item command="/user/assets"><el-icon><FolderOpened /></el-icon>资产管理</el-dropdown-item>
          <el-dropdown-item command="/user/models"><el-icon><SetUp /></el-icon>模型配置</el-dropdown-item>
          <el-dropdown-item command="/user/agent-policy"><el-icon><SetUp /></el-icon>Agent 策略</el-dropdown-item>
          <el-dropdown-item command="/user/research"><el-icon><Bell /></el-icon>研究与审批</el-dropdown-item>
          <template v-if="auth.isAdmin">
            <el-dropdown-item command="system-settings" divided><el-icon><Tools /></el-icon>系统设置</el-dropdown-item>
          </template>
          <el-dropdown-item command="logout" divided>
            <el-icon><SwitchButton /></el-icon>
            退出登录
          </el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </div>
</template>

<style scoped>
.user-settings-menu {
  min-width: 0;
}

.user-settings-menu :deep(.el-dropdown) {
  display: block;
  width: 100%;
}

.user-trigger {
  align-items: center;
  background: transparent;
  border: 0;
  border-radius: var(--byq-radius-sm);
  color: var(--byq-text);
  cursor: pointer;
  display: flex;
  gap: 0.55rem;
  padding: 0.45rem 0.5rem;
  text-align: left;
  width: 100%;
}

.user-trigger:hover {
  background: var(--byq-surface-subtle);
}

.is-sidebar .user-trigger {
  background: var(--byq-surface-subtle);
  border: 1px solid var(--byq-border-subtle);
  padding: 0.55rem 0.6rem;
}

.is-sidebar .user-trigger:hover {
  background: var(--byq-brand-soft);
  border-color: var(--byq-border);
}

.user-avatar {
  align-items: center;
  background: var(--byq-brand);
  border-radius: 999px;
  color: var(--byq-on-brand);
  display: inline-flex;
  flex: 0 0 auto;
  font-size: 14px;
  font-weight: 800;
  height: 32px;
  justify-content: center;
  width: 32px;
}

.is-sidebar .user-avatar {
  font-size: 15px;
  height: 36px;
  width: 36px;
}

.user-copy {
  display: grid;
  line-height: 1.25;
  min-width: 0;
}

.user-copy strong {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-copy small {
  color: var(--byq-text-muted);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-caret {
  color: var(--byq-text-muted);
  margin-left: auto;
}

.workspace-orientation {
  border-bottom: 1px solid var(--byq-border-subtle);
  display: grid;
  gap: 2px;
  list-style: none;
  margin: 0 8px 6px;
  padding: 8px 12px 10px;
}

.workspace-orientation span,
.workspace-orientation small {
  color: var(--byq-text-muted);
  font-size: 11px;
}

.workspace-orientation strong {
  color: var(--byq-text);
  font-size: 13px;
}

.is-mobile .user-trigger {
  align-items: center;
  flex-direction: row;
  gap: 0.35rem;
  justify-content: center;
  padding: 0.3rem;
}

.is-mobile .user-avatar {
  font-size: 12px;
  height: 22px;
  width: 22px;
}

.mobile-label {
  color: var(--byq-text-muted);
  font-size: 12px;
  font-weight: 700;
}
</style>
