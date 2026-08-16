<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import { CaretBottom, SwitchButton } from "@element-plus/icons-vue";
import { useAuthStore } from "@/stores/auth";

const props = withDefaults(
  defineProps<{
    variant?: "sidebar" | "mobile";
    mobileLabel?: string;
  }>(),
  {
    variant: "sidebar",
    mobileLabel: "我的",
  },
);

const auth = useAuthStore();
const router = useRouter();

const displayName = computed(() => auth.user?.subject ?? "未登录");
const avatarText = computed(() => displayName.value.slice(0, 1).toUpperCase() || "B");

async function handleCommand(command: string) {
  if (command === "logout") {
    await auth.logout();
    await router.push({ name: "login" });
  }
}
</script>

<template>
  <div class="user-settings-menu" :class="`is-${props.variant}`">
    <el-dropdown trigger="click" placement="top-start" @command="handleCommand">
      <button type="button" class="user-trigger" :aria-label="`用户设置：${displayName}`">
        <span class="user-avatar">{{ avatarText }}</span>
        <span v-if="props.variant === 'mobile' && props.mobileLabel" class="mobile-label">
          {{ props.mobileLabel }}
        </span>
        <span v-else class="user-copy">
          <strong>{{ displayName }}</strong>
          <small>BeyondQuant 产品账户</small>
        </span>
        <el-icon v-if="props.variant !== 'mobile'" class="user-caret"><CaretBottom /></el-icon>
      </button>
      <template #dropdown>
        <el-dropdown-menu>
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
  color: #fff;
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
