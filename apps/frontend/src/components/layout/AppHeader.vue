<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Bell } from "@element-plus/icons-vue";
import { getSettingsStatus } from "@/api/settings";
import { useAuthStore } from "@/stores/auth";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const pendingApprovals = ref(0);

const meta = computed(() => {
  const value = route.meta as Record<string, unknown>;
  return {
    kicker: typeof value.kicker === "string" ? value.kicker : "BeyondQuant",
    title: typeof value.title === "string" ? value.title : "BeyondQuant",
    subtitle: typeof value.subtitle === "string" ? value.subtitle : "",
  };
});

onMounted(async () => {
  try {
    const status = await getSettingsStatus(auth.token);
    pendingApprovals.value = status.approval_inbox.pending;
  } catch {
    pendingApprovals.value = 0;
  }
});
</script>

<template>
  <header class="app-header">
    <div class="header-intro">
      <div class="header-kicker">{{ meta.kicker }}</div>
      <h1 class="header-title">{{ meta.title }}</h1>
      <p v-if="meta.subtitle" class="header-subtitle">{{ meta.subtitle }}</p>
    </div>
    <div class="header-right">
      <el-tooltip content="审批收件箱" placement="bottom">
        <button type="button" class="approval-trigger" aria-label="审批收件箱" @click="router.push('/research-center')">
          <el-badge :value="pendingApprovals" :hidden="pendingApprovals === 0">
            <el-icon><Bell /></el-icon>
          </el-badge>
        </button>
      </el-tooltip>
    </div>
  </header>
</template>

<style scoped>
.app-header {
  align-items: center;
  background: var(--byq-surface);
  border-bottom: 1px solid var(--byq-border);
  display: flex;
  flex: 0 0 auto;
  height: 64px;
  justify-content: space-between;
  min-height: 64px;
  padding: 0.55rem 1.25rem;
}

.header-intro {
  min-width: 0;
}

.header-kicker {
  color: var(--byq-brand);
  font-size: 11px;
  font-weight: 850;
  letter-spacing: 0.05em;
  line-height: 1.3;
  text-transform: uppercase;
}

.header-title {
  color: var(--byq-text);
  font-size: 19px;
  font-weight: 850;
  line-height: 1.2;
  margin: 0.05rem 0 0;
}

.header-subtitle {
  color: var(--byq-text-muted);
  font-size: 12px;
  line-height: 1.4;
  margin: 0.15rem 0 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-right {
  display: flex;
  gap: 0.6rem;
  margin-left: 1rem;
}

.approval-trigger {
  align-items: center;
  background: var(--byq-surface);
  border: 1px solid var(--byq-border);
  border-radius: var(--byq-radius-sm);
  color: var(--byq-text-muted);
  cursor: pointer;
  display: inline-flex;
  height: 34px;
  justify-content: center;
  width: 34px;
}

.approval-trigger:hover {
  background: var(--byq-brand-soft);
  border-color: var(--byq-border);
}

.approval-trigger .el-icon {
  font-size: 18px;
}

@media (max-width: 767px) {
  .app-header {
    min-height: 56px;
    padding: 0.45rem 0.9rem;
  }

  .header-title {
    font-size: 16px;
  }

  .header-subtitle {
    display: none;
  }
}
</style>
