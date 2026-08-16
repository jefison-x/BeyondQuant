<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Menu } from "@element-plus/icons-vue";
import { businessNavGroups, findActiveNavItem } from "@/router/navigation";
import { useAgentStore } from "@/stores/agent";
import UserSettingsMenu from "./UserSettingsMenu.vue";

defineProps<{ isCollapsed: boolean }>();
const emit = defineEmits<{ (event: "toggle-collapse"): void }>();

const route = useRoute();
const router = useRouter();
const agent = useAgentStore();

const activeIndex = computed(() => findActiveNavItem(route.path));
const openGroups = businessNavGroups.map((group) => group.index);

function handleMenuSelect(index: string) {
  if (route.path !== index) {
    void router.push(index);
  }
}

function openSession(sessionId: string) {
  agent.setActiveSession(sessionId);
  if (route.path !== "/agent") {
    void router.push({ path: "/agent", query: { ...route.query, session: sessionId } });
  }
}
</script>

<template>
  <aside class="app-sidebar" :class="{ collapsed: isCollapsed }">
    <div class="sidebar-header">
      <div class="brand-mark">B</div>
      <div v-if="!isCollapsed" class="brand-copy">
        <span class="logo-text">BeyondQuant</span>
        <span class="logo-subtitle">Research OS</span>
      </div>
      <el-button
        class="collapse-toggle"
        size="small"
        aria-label="折叠菜单"
        @click="emit('toggle-collapse')"
      >
        <el-icon><Menu /></el-icon>
      </el-button>
    </div>

    <el-menu
      :default-active="activeIndex"
      :default-openeds="openGroups"
      :collapse="isCollapsed"
      :collapse-transition="false"
      class="sidebar-menu"
      @select="handleMenuSelect"
    >
      <el-sub-menu v-for="group in businessNavGroups" :key="group.index" :index="group.index">
        <template #title>
          <el-icon><component :is="group.icon" /></el-icon>
          <span>{{ group.label }}</span>
        </template>
        <el-menu-item v-for="item in group.items" :key="item.to" :index="item.to">
          {{ item.label }}
        </el-menu-item>
      </el-sub-menu>
    </el-menu>

    <section v-if="!isCollapsed && agent.sessions.length" class="sidebar-history">
      <div class="history-heading">历史会话</div>
      <div class="history-list">
        <button
          v-for="session in agent.sessions"
          :key="session.session_id"
          type="button"
          class="history-row"
          :class="{ active: agent.activeSessionId === session.session_id }"
          @click="openSession(session.session_id)"
        >
          {{ session.session_id.slice(-8) }}
        </button>
      </div>
    </section>

    <div class="sidebar-user-bar">
      <UserSettingsMenu class="sidebar-user-menu" />
    </div>
  </aside>
</template>

<style scoped>
.app-sidebar {
  background: var(--byq-surface);
  border-right: 1px solid var(--byq-border);
  display: flex;
  flex-direction: column;
  height: 100vh;
  transition: all 0.3s ease;
  width: 260px;
  z-index: 50;
}

.app-sidebar.collapsed {
  width: 68px;
}

.sidebar-header {
  align-items: center;
  border-bottom: 1px solid var(--byq-border);
  display: flex;
  gap: 0.7rem;
  height: 64px;
  min-height: 64px;
  padding: 0 0.85rem;
}

.brand-mark {
  align-items: center;
  background: var(--byq-brand);
  border-radius: 7px;
  color: #ffffff;
  display: inline-flex;
  flex: 0 0 auto;
  font-size: 15px;
  font-weight: 900;
  height: 32px;
  justify-content: center;
  width: 32px;
}

.brand-copy {
  display: grid;
  line-height: 1.2;
  min-width: 0;
}

.logo-text {
  color: var(--byq-text);
  font-size: 14px;
  font-weight: 850;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.logo-subtitle {
  color: var(--byq-text-soft);
  font-size: 11px;
  font-weight: 700;
  margin-top: 1px;
}

.collapse-toggle {
  border: 1px solid var(--byq-border);
  height: 32px;
  margin-left: auto;
  padding: 0;
  width: 32px;
}

.sidebar-menu {
  --el-menu-active-color: var(--byq-brand);
  --el-menu-bg-color: transparent;
  --el-menu-hover-bg-color: var(--byq-brand-soft);
  --el-menu-text-color: #374151;
  border-right: none;
  flex-shrink: 0;
  padding: 0.75rem 0.55rem;
}

.sidebar-menu :deep(.el-menu-item) {
  border-radius: 7px;
  height: 38px;
  line-height: 38px;
  margin: 2px 0;
  padding: 0 0.75rem !important;
}

.sidebar-menu :deep(.el-sub-menu > .el-menu > .el-menu-item) {
  padding-left: 2.25rem !important;
}

.sidebar-menu :deep(.el-menu-item.is-active) {
  background: var(--byq-brand-soft);
  color: var(--byq-brand);
  font-weight: 800;
}

.sidebar-menu :deep(.el-menu-item .el-icon) {
  color: inherit;
  font-size: 17px;
}

.app-sidebar.collapsed .sidebar-menu .el-sub-menu__title,
.app-sidebar.collapsed .sidebar-menu .el-menu-item {
  justify-content: center;
}

.app-sidebar.collapsed .sidebar-menu :deep(.el-sub-menu > .el-menu > .el-menu-item) {
  padding-left: 0 !important;
}

.app-sidebar.collapsed .sidebar-menu .el-menu-item span {
  height: 0;
  opacity: 0;
  transition: all 0.3s ease;
}

.sidebar-user-bar {
  align-items: center;
  border-top: 1px solid var(--byq-border);
  display: flex;
  gap: 0.25rem;
  margin-top: auto;
  padding: 0.55rem 0.6rem;
}

.sidebar-user-menu {
  flex: 1;
  min-width: 0;
}

.sidebar-history {
  border-top: 1px solid var(--byq-border-subtle);
  margin-top: 0.75rem;
  padding: 0.75rem 0.75rem 0;
}

.history-heading {
  color: var(--byq-text-soft);
  font-size: 11px;
  font-weight: 850;
  letter-spacing: 0.04em;
  padding: 0 0.45rem 0.4rem;
  text-transform: uppercase;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.history-row {
  background: transparent;
  border: 0;
  border-radius: var(--byq-radius-sm);
  color: var(--byq-text);
  cursor: pointer;
  font-size: 12px;
  overflow: hidden;
  padding: 0.45rem;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-row:hover,
.history-row.active {
  background: var(--byq-brand-soft);
  color: var(--byq-brand);
}
</style>
