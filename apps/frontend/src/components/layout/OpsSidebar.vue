<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  Coin,
  Connection,
  DataAnalysis,
  Lock,
  Menu,
  Money,
  Operation,
  SetUp,
  Share,
  Tools,
} from "@element-plus/icons-vue";

const route = useRoute();
const router = useRouter();

defineProps<{ isCollapsed: boolean }>();
const emit = defineEmits<{
  (event: "toggle-collapse"): void;
  (event: "navigate"): void;
}>();

const groups = [
  {
    index: "infrastructure",
    label: "基础设施",
    icon: Connection,
    items: [
      { to: "/admin/database", label: "数据库管理", icon: Connection },
      { to: "/admin/sources", label: "数据源管理", icon: Operation },
      { to: "/admin/cache", label: "缓存管理", icon: Coin },
    ],
  },
  {
    index: "agent-platform",
    label: "智能体平台",
    icon: Tools,
    items: [
      { to: "/admin/models", label: "模型运维", icon: SetUp },
      { to: "/admin/agents", label: "智能体运维", icon: Tools },
      { to: "/admin/budget", label: "执行预算", icon: Money },
      { to: "/admin/runtime", label: "运行诊断", icon: DataAnalysis },
      { to: "/admin/graphs", label: "Graph 工作流", icon: Share },
    ],
  },
  {
    index: "permission-audit",
    label: "权限与审计",
    icon: Lock,
    items: [{ to: "/admin/access", label: "权限与审计", icon: Lock }],
  },
];

const activeIndex = computed(() => {
  if (route.path.startsWith("/admin/database")) return "/admin/database";
  if (route.path.startsWith("/admin/sources")) return "/admin/sources";
  if (route.path.startsWith("/admin/cache")) return "/admin/cache";
  if (route.path.startsWith("/admin/models")) return "/admin/models";
  if (route.path.startsWith("/admin/agents")) return "/admin/agents";
  if (route.path.startsWith("/admin/budget")) return "/admin/budget";
  if (route.path.startsWith("/admin/runtime")) return "/admin/runtime";
  if (route.path.startsWith("/admin/graphs")) return "/admin/graphs";
  return "/admin/access";
});

function handleSelect(index: string) {
  if (route.path !== index) void router.push(index);
  emit("navigate");
}
</script>

<template>
  <aside class="app-sidebar ops-sidebar" :class="{ collapsed: isCollapsed }">
    <div class="sidebar-header">
      <div class="brand-mark">B</div>
      <div v-if="!isCollapsed" class="brand-copy">
        <span class="logo-text">BeyondQuant</span>
        <span class="logo-subtitle">System Operations</span>
      </div>
      <el-button class="collapse-toggle" size="small" aria-label="折叠菜单" @click="emit('toggle-collapse')">
        <el-icon><Menu /></el-icon>
      </el-button>
    </div>

    <el-menu
      :default-active="activeIndex"
      :default-openeds="groups.map((group) => group.index)"
      :collapse="isCollapsed"
      :collapse-transition="false"
      class="sidebar-menu ops-menu"
      @select="handleSelect"
    >
      <el-sub-menu v-for="group in groups" :key="group.index" :index="group.index">
        <template #title>
          <el-icon><component :is="group.icon" /></el-icon>
          <span>{{ group.label }}</span>
        </template>
        <el-menu-item v-for="item in group.items" :key="item.to" :index="item.to">
          {{ item.label }}
        </el-menu-item>
      </el-sub-menu>
    </el-menu>
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
  color: #fff;
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
}

.logo-subtitle {
  color: var(--byq-text-soft);
  font-size: 11px;
  font-weight: 700;
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
  flex: 1;
  min-height: 0;
  overflow-y: auto;
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
</style>
