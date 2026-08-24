<script setup lang="ts">
import { computed, onMounted } from "vue";
import { ElMessage } from "element-plus";
import type { AccentTheme, ColorMode } from "@/api/types";
import { ACCENT_THEMES, COLOR_MODES, useAppearanceStore } from "@/stores/appearance";
import { useUnsavedChanges } from "@/composables/useUnsavedChanges";

const appearance = useAppearanceStore();
const modeLabels: Record<ColorMode, { name: string; description: string }> = {
  system: { name: "跟随系统", description: "随设备浅色或深色设置自动切换" },
  light: { name: "浅色", description: "始终使用明亮工作区" },
  dark: { name: "深色", description: "始终使用低亮度工作区" },
};
const accentLabels: Record<AccentTheme, string> = {
  emerald: "翡翠", ocean: "海洋", indigo: "靛青", amber: "琥珀", graphite: "石墨",
};
const dirty = computed(() =>
  appearance.preferences.color_mode !== appearance.savedPreferences.color_mode
  || appearance.preferences.accent_theme !== appearance.savedPreferences.accent_theme,
);
useUnsavedChanges(dirty, { onDiscard: () => appearance.revert() });

async function save() {
  try {
    await appearance.save();
    ElMessage.success("外观设置已同步到你的账户");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "外观设置保存失败");
  }
}

onMounted(async () => {
  if (appearance.hydrated) return;
  try { await appearance.load(); }
  catch { ElMessage.error("暂时无法读取账户外观设置"); }
});
</script>

<template>
  <div class="appearance-page" v-loading="appearance.loading">
    <el-card shadow="never">
      <template #header>
        <div class="appearance-header">
          <div><strong>外观与主题</strong><p>选择会立即预览；保存后在你的其他设备登录时自动恢复。</p></div>
          <el-tag type="info" effect="plain">ui-preferences.v1</el-tag>
        </div>
      </template>

      <section aria-labelledby="color-mode-heading">
        <h2 id="color-mode-heading">显示模式</h2>
        <div class="mode-grid">
          <button
            v-for="mode in COLOR_MODES"
            :key="mode"
            type="button"
            class="choice-card"
            :class="{ active: appearance.preferences.color_mode === mode }"
            :aria-pressed="appearance.preferences.color_mode === mode"
            @click="appearance.preview({ color_mode: mode })"
          >
            <span class="mode-preview" :class="`mode-${mode}`"><i /><i /><i /></span>
            <strong>{{ modeLabels[mode].name }}</strong>
            <small>{{ modeLabels[mode].description }}</small>
          </button>
        </div>
      </section>

      <el-divider />

      <section aria-labelledby="accent-heading">
        <h2 id="accent-heading">主题颜色</h2>
        <p class="section-note">强调色只用于主操作、选中态和品牌标识，不改变成功、警告、错误或审批语义。</p>
        <div class="accent-grid">
          <button
            v-for="accent in ACCENT_THEMES"
            :key="accent"
            type="button"
            class="accent-choice"
            :class="[{ active: appearance.preferences.accent_theme === accent }, `swatch-${accent}`]"
            :aria-pressed="appearance.preferences.accent_theme === accent"
            @click="appearance.preview({ accent_theme: accent })"
          >
            <span class="swatch" />
            <span>{{ accentLabels[accent] }}</span>
          </button>
        </div>
      </section>

      <div class="theme-proof" aria-label="主题语义预览">
        <div><strong>实时预览</strong><small>所有页面、卡片和对话使用同一组语义变量。</small></div>
        <el-button type="primary">主要操作</el-button>
        <el-tag type="success">成功</el-tag>
        <el-tag type="warning">待确认</el-tag>
        <el-tag type="danger">风险</el-tag>
      </div>

      <div class="appearance-actions">
        <span>{{ dirty ? "存在尚未保存的预览" : "已与账户设置同步" }}</span>
        <div>
          <el-button :disabled="!dirty || appearance.saving" @click="appearance.revert">撤销预览</el-button>
          <el-button type="primary" :disabled="!dirty" :loading="appearance.saving" @click="save">保存外观</el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.appearance-page { min-width: 0; }
.appearance-header, .appearance-actions, .theme-proof { align-items: center; display: flex; gap: 12px; justify-content: space-between; }
.appearance-header p, .section-note { color: var(--byq-text-muted); font-size: 12px; margin: 4px 0 0; }
h2 { color: var(--byq-text); font-size: 15px; margin: 0 0 12px; }
.mode-grid { display: grid; gap: 10px; grid-template-columns: repeat(3, minmax(0, 1fr)); }
.choice-card, .accent-choice { background: var(--byq-surface); border: 1px solid var(--byq-border); color: var(--byq-text); cursor: pointer; font: inherit; text-align: left; }
.choice-card { border-radius: 10px; display: grid; gap: 6px; padding: 12px; }
.choice-card:hover, .choice-card.active, .accent-choice:hover, .accent-choice.active { border-color: var(--byq-brand); box-shadow: 0 0 0 1px var(--byq-brand); }
.choice-card small { color: var(--byq-text-muted); font-size: 11px; line-height: 1.45; }
.mode-preview { background: var(--byq-surface-muted); border: 1px solid var(--byq-border); border-radius: 7px; display: grid; gap: 4px; grid-template-columns: 24% 1fr; height: 54px; overflow: hidden; padding: 5px; }
.mode-preview i:first-child { background: var(--byq-brand); border-radius: 4px; grid-row: span 2; }
.mode-preview i { background: var(--byq-surface); border-radius: 4px; }
.mode-dark { background: var(--byq-preview-dark-bg); border-color: var(--byq-preview-dark-border); }
.mode-dark i:not(:first-child) { background: var(--byq-preview-dark-surface); }
.mode-light { background: var(--byq-preview-light-bg); border-color: var(--byq-preview-light-border); }
.mode-light i:not(:first-child) { background: var(--byq-preview-light-surface); }
.mode-system { background: linear-gradient(110deg, var(--byq-preview-light-bg) 49%, var(--byq-preview-dark-bg) 51%); }
.accent-grid { display: flex; flex-wrap: wrap; gap: 9px; margin-top: 12px; }
.accent-choice { align-items: center; border-radius: 9px; display: flex; gap: 8px; min-width: 110px; padding: 9px 11px; }
.swatch { background: var(--swatch); border-radius: 999px; height: 18px; width: 18px; }
.swatch-emerald { --swatch: var(--byq-palette-emerald); }.swatch-ocean { --swatch: var(--byq-palette-ocean); }.swatch-indigo { --swatch: var(--byq-palette-indigo); }.swatch-amber { --swatch: var(--byq-palette-amber); }.swatch-graphite { --swatch: var(--byq-palette-graphite); }
.theme-proof { background: var(--byq-surface-muted); border-radius: 10px; flex-wrap: wrap; margin-top: 20px; padding: 13px; }
.theme-proof > div:first-child { display: grid; margin-right: auto; }
.theme-proof small { color: var(--byq-text-muted); font-size: 11px; }
.appearance-actions { border-top: 1px solid var(--byq-border-subtle); margin-top: 18px; padding-top: 15px; }
.appearance-actions > span { color: var(--byq-text-muted); font-size: 11px; }
@media (max-width: 720px) { .mode-grid { grid-template-columns: 1fr; }.appearance-actions { align-items: stretch; flex-direction: column; }.appearance-actions > div { display: flex; }.appearance-actions .el-button { flex: 1; } }
</style>
