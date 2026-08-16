<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Grid } from "@element-plus/icons-vue";
import { businessNavGroups } from "@/router/navigation";
import UserSettingsMenu from "./UserSettingsMenu.vue";

const route = useRoute();
const router = useRouter();
const menuVisible = ref(false);

function goPage(path: string) {
  menuVisible.value = false;
  if (route.path !== path) {
    void router.push(path);
  }
}
</script>

<template>
  <nav class="app-bottom-nav">
    <div class="bottom-nav-item">
      <el-popover v-model:visible="menuVisible" placement="top-start" trigger="click" popper-class="nav-popper">
        <template #reference>
          <button type="button" class="nav-cell" aria-label="功能菜单">
            <el-icon><Grid /></el-icon>
            <span>菜单</span>
          </button>
        </template>
        <div class="pop-panel">
          <div class="pop-heading">功能页面</div>
          <div class="pop-list">
            <div v-for="group in businessNavGroups" :key="group.index" class="pop-group">
              <div class="pop-group-title">{{ group.label }}</div>
              <button
                v-for="item in group.items"
                :key="item.to"
                type="button"
                class="pop-list-row"
                @click="goPage(item.to)"
              >
                <el-icon><component :is="item.icon" /></el-icon>
                <span>{{ item.label }}</span>
              </button>
            </div>
          </div>
        </div>
      </el-popover>
    </div>

    <div class="bottom-nav-item">
      <UserSettingsMenu variant="mobile" mobile-label="我的" placement="top-end" />
    </div>
  </nav>
</template>

<style scoped>
.app-bottom-nav {
  background: var(--byq-surface);
  border-top: 1px solid var(--byq-border);
  bottom: 0;
  display: flex;
  height: 56px;
  justify-content: space-around;
  left: 0;
  position: fixed;
  right: 0;
  z-index: 60;
}

.bottom-nav-item {
  align-items: stretch;
  display: flex;
  flex: 1;
  justify-content: center;
}

.nav-cell {
  align-items: center;
  background: transparent;
  border: 0;
  color: var(--byq-text-muted);
  cursor: pointer;
  display: flex;
  flex: 1;
  flex-direction: column;
  font-size: 12px;
  gap: 2px;
  justify-content: center;
}

.nav-cell .el-icon {
  color: var(--byq-text);
  font-size: 20px;
}
</style>

<style>
.nav-popper {
  max-width: min(340px, calc(100vw - 16px));
}

.pop-panel {
  max-height: 70vh;
  overflow-y: auto;
}

.pop-heading {
  color: var(--byq-text-muted);
  font-size: 12px;
  font-weight: 800;
  padding: 0.35rem 0.5rem 0.5rem;
}

.pop-list {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.pop-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.pop-group-title {
  color: var(--byq-text-soft);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.04em;
  padding: 0.4rem 0.5rem 0.2rem;
}

.pop-list-row {
  align-items: center;
  background: transparent;
  border: 0;
  border-radius: var(--byq-radius-sm);
  color: var(--byq-text);
  cursor: pointer;
  display: flex;
  gap: 0.5rem;
  padding: 0.45rem 0.5rem;
  text-align: left;
  width: 100%;
}

.pop-list-row:hover {
  background: var(--byq-brand-soft);
}

.pop-list-row .el-icon {
  color: var(--byq-text-muted);
  font-size: 16px;
}
</style>
