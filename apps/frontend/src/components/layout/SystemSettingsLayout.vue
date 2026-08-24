<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Close } from "@element-plus/icons-vue";
import {
  findSystemSettingsItem,
  systemSettingsGroups,
} from "@/router/systemSettingsNavigation";

const route = useRoute();
const router = useRouter();
const isMobile = ref(false);

const activeItem = computed(() => findSystemSettingsItem(route.path));

function updateViewport() {
  isMobile.value = window.innerWidth <= 767;
}

function navigate(path: string) {
  if (path === route.path) return;
  void router.push({ path, query: route.query });
}

function safeReturnPath(): string {
  const candidate = typeof route.query.returnTo === "string" ? route.query.returnTo : "";
  if (
    candidate.startsWith("/") &&
    !candidate.startsWith("//") &&
    !candidate.startsWith("/settings/system") &&
    !candidate.startsWith("/admin")
  ) return candidate;
  return "/agent";
}

function closeSettings() {
  void router.push(safeReturnPath());
}

onMounted(() => {
  updateViewport();
  window.addEventListener("resize", updateViewport);
});

onUnmounted(() => window.removeEventListener("resize", updateViewport));
</script>

<template>
  <el-dialog
    :model-value="true"
    :fullscreen="isMobile"
    :show-close="false"
    append-to-body
    class="system-settings-dialog"
    width="min(1240px, 94vw)"
    @close="closeSettings"
  >
    <template #header="{ titleId }">
      <header class="settings-header">
        <div>
          <span>管理员工作区</span>
          <h1 :id="titleId">系统设置</h1>
          <p>Product API 去敏投影 · RBAC 与审计保持有效</p>
        </div>
        <el-button aria-label="关闭系统设置" circle @click="closeSettings">
          <el-icon><Close /></el-icon>
        </el-button>
      </header>
    </template>

    <div class="settings-mobile-nav">
      <label for="system-settings-section">设置分区</label>
      <el-select
        id="system-settings-section"
        :model-value="activeItem.path"
        aria-label="系统设置分区"
        @change="navigate"
      >
        <el-option-group v-for="group in systemSettingsGroups" :key="group.label" :label="group.label">
          <el-option v-for="item in group.items" :key="item.path" :label="item.label" :value="item.path" />
        </el-option-group>
      </el-select>
    </div>

    <div class="settings-grid">
      <nav class="settings-nav" aria-label="系统设置导航">
        <section v-for="group in systemSettingsGroups" :key="group.label">
          <span class="group-label">{{ group.label }}</span>
          <button
            v-for="item in group.items"
            :key="item.path"
            type="button"
            :class="{ active: item.path === activeItem.path }"
            :aria-current="item.path === activeItem.path ? 'page' : undefined"
            @click="navigate(item.path)"
          >
            <el-icon><component :is="item.icon" /></el-icon>
            <span><strong>{{ item.label }}</strong><small>{{ item.description }}</small></span>
          </button>
        </section>
      </nav>

      <section class="settings-content" :aria-labelledby="`settings-title-${activeItem.path.split('/').pop()}`">
        <div class="section-heading">
          <div>
            <span>系统设置</span>
            <h2 :id="`settings-title-${activeItem.path.split('/').pop()}`">{{ activeItem.label }}</h2>
            <p>{{ activeItem.description }}</p>
          </div>
          <el-tag effect="plain">管理员专用</el-tag>
        </div>
        <div class="section-body"><RouterView /></div>
      </section>
    </div>
  </el-dialog>
</template>

<style scoped>
.settings-header { align-items: center; display: flex; justify-content: space-between; padding: 2px 4px; }
.settings-header span, .section-heading > div > span { color: var(--byq-brand); font-size: 11px; font-weight: 850; letter-spacing: .12em; text-transform: uppercase; }
.settings-header h1 { color: var(--byq-text); font-size: 22px; margin: 3px 0; }
.settings-header p, .section-heading p { color: var(--byq-text-muted); font-size: 12px; margin: 0; }
.settings-grid { display: grid; grid-template-columns: 248px minmax(0, 1fr); height: min(74vh, 820px); min-height: 560px; }
.settings-nav { border-right: 1px solid var(--byq-border); overflow-y: auto; padding: 8px 12px 16px 0; }
.settings-nav section { display: grid; gap: 3px; margin-bottom: 16px; }
.group-label { color: var(--byq-text-muted); font-size: 10px; font-weight: 800; letter-spacing: .08em; padding: 0 10px 5px; text-transform: uppercase; }
.settings-nav button { align-items: center; background: transparent; border: 0; border-radius: 8px; color: var(--byq-text-muted); cursor: pointer; display: grid; gap: 9px; grid-template-columns: 20px minmax(0, 1fr); padding: 8px 10px; text-align: left; width: 100%; }
.settings-nav button:hover, .settings-nav button.active { background: var(--byq-brand-soft); color: var(--byq-brand); }
.settings-nav button > span { display: grid; gap: 1px; min-width: 0; }
.settings-nav strong { font-size: 12px; }
.settings-nav small { color: var(--byq-text-muted); font-size: 9px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.settings-content { display: flex; flex-direction: column; min-height: 0; min-width: 0; }
.section-heading { align-items: center; border-bottom: 1px solid var(--byq-border); display: flex; justify-content: space-between; padding: 10px 4px 14px 20px; }
.section-heading h2 { color: var(--byq-text); font-size: 21px; margin: 3px 0; }
.section-body { flex: 1; min-height: 0; overflow-y: auto; padding: 18px 4px 18px 20px; }
.settings-mobile-nav { display: none; }
@media (max-width: 767px) {
  .settings-header h1 { font-size: 20px; }
  .settings-header p { max-width: 250px; }
  .settings-mobile-nav { background: var(--byq-surface-subtle); border-bottom: 1px solid var(--byq-border); display: grid; gap: 5px; padding: 10px 14px; }
  .settings-mobile-nav label { color: var(--byq-text-muted); font-size: 11px; font-weight: 750; }
  .settings-mobile-nav :deep(.el-select) { width: 100%; }
  .settings-mobile-nav :deep(.el-select__wrapper) { background: var(--byq-surface); }
  .settings-mobile-nav :deep(.el-select__selected-item) { color: var(--byq-text); }
  .settings-grid { display: block; height: auto; min-height: 0; }
  .settings-nav { display: none; }
  .settings-content { height: calc(100vh - 174px); }
  .section-heading { padding: 12px 14px; }
  .section-heading h2 { font-size: 19px; }
  .section-heading .el-tag { display: none; }
  .section-body { padding: 14px; }
}
</style>

<style>
.system-settings-dialog { --el-dialog-bg-color: var(--byq-surface); border: 1px solid var(--byq-border); border-radius: 14px; margin-top: 5vh; overflow: hidden; }
.system-settings-dialog .el-dialog__header { border-bottom: 1px solid var(--byq-border); margin: 0; padding: 14px 18px; }
.system-settings-dialog .el-dialog__body { padding: 0 18px; }
@media (max-width: 767px) {
  .system-settings-dialog { border: 0; border-radius: 0; margin: 0; }
  .system-settings-dialog .el-dialog__header { padding: 10px 14px; }
  .system-settings-dialog .el-dialog__body { padding: 0; }
}
</style>
