<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Bell, Menu } from "@element-plus/icons-vue";
import { getSettingsStatus } from "@/api/settings";
import { useAuthStore } from "@/stores/auth";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const pendingApprovals = ref(0);
defineProps<{ showMenu?: boolean }>();
const emit = defineEmits<{ (event: "toggle-menu"): void }>();

const meta = computed(() => {
  const value = route.meta as Record<string, unknown>;
  return {
    title: typeof value.title === "string" ? value.title : "BeyondQuant",
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
    <div class="header-leading">
      <button
        v-if="showMenu"
        type="button"
        class="mobile-menu-trigger"
        aria-label="打开产品导航"
        @click="emit('toggle-menu')"
      >
        <el-icon><Menu /></el-icon>
      </button>
      <div class="header-intro">
        <h1 class="header-title">{{ meta.title }}</h1>
      </div>
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
  height: 52px;
  justify-content: space-between;
  min-height: 52px;
  padding: 0.4rem 1rem;
}

.header-intro {
  min-width: 0;
}

.header-leading {
  align-items: center;
  display: flex;
  min-width: 0;
}

.mobile-menu-trigger {
  align-items: center;
  background: var(--byq-surface);
  border: 1px solid var(--byq-border);
  border-radius: var(--byq-radius-sm);
  color: var(--byq-text-muted);
  cursor: pointer;
  display: inline-flex;
  flex: 0 0 auto;
  height: 34px;
  justify-content: center;
  margin-right: 0.65rem;
  width: 34px;
}

.header-title {
  color: var(--byq-text);
  font-size: 16px;
  font-weight: 850;
  line-height: 1.2;
  margin: 0;
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
    min-height: 52px;
    padding: 0.45rem 0.9rem;
  }

  .header-title {
    font-size: 16px;
  }

}
</style>
