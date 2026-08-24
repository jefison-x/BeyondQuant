<script setup lang="ts">
withDefaults(defineProps<{
  eyebrow: string;
  title: string;
  description: string;
  catalogLabel: string;
  count?: number;
  returnLabel?: string;
}>(), {
  count: 0,
  returnLabel: "返回投研对话",
});

const emit = defineEmits<{ return: [] }>();
</script>

<template>
  <section class="management-workspace">
    <header class="workspace-hero">
      <div class="workspace-copy">
        <span>{{ eyebrow }}</span>
        <h2>{{ title }}</h2>
        <p>{{ description }}</p>
      </div>
      <div class="workspace-actions">
        <el-button v-if="$slots.return" plain @click="emit('return')">
          <slot name="return">{{ returnLabel }}</slot>
        </el-button>
        <slot name="actions" />
      </div>
    </header>

    <div class="workspace-summary" aria-label="工作区摘要">
      <span>{{ catalogLabel }}</span>
      <strong>{{ count }}</strong>
      <small><slot name="summary">真实 Product 数据</slot></small>
    </div>

    <div class="management-grid">
      <aside class="management-catalog" :aria-label="catalogLabel">
        <slot name="catalog" />
      </aside>
      <section class="management-detail" :aria-label="`${title}详情`">
        <slot name="detail" />
      </section>
    </div>
  </section>
</template>

<style scoped>
.management-workspace { display: grid; gap: 12px; min-width: 0; }
.workspace-hero { align-items: center; background: var(--byq-surface); border: 1px solid var(--byq-border); border-radius: 12px; display: flex; gap: 18px; justify-content: space-between; padding: 16px 18px; }
.workspace-copy { min-width: 0; }
.workspace-copy > span { color: var(--byq-brand); font-size: 10px; font-weight: 850; letter-spacing: .12em; text-transform: uppercase; }
.workspace-copy h2 { color: var(--byq-text); font-size: 20px; line-height: 1.25; margin: 3px 0; }
.workspace-copy p { color: var(--byq-text-muted); font-size: 12px; line-height: 1.55; margin: 0; }
.workspace-actions { align-items: center; display: flex; flex-shrink: 0; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
.workspace-summary { align-items: baseline; color: var(--byq-text-muted); display: flex; font-size: 11px; gap: 7px; padding: 0 4px; }
.workspace-summary strong { color: var(--byq-text); font-size: 17px; }
.workspace-summary small { color: var(--byq-text-muted); font-size: 11px; margin-left: auto; }
.management-grid { align-items: start; display: grid; gap: 12px; grid-template-columns: minmax(340px, .78fr) minmax(0, 1.22fr); min-width: 0; }
.management-catalog, .management-detail { display: grid; gap: 12px; min-width: 0; }
@media (max-width: 1040px) {
  .management-grid { grid-template-columns: minmax(310px, .72fr) minmax(0, 1.28fr); }
}
@media (max-width: 900px) {
  .workspace-hero { align-items: flex-start; flex-direction: column; padding: 14px; }
  .workspace-actions { justify-content: flex-start; width: 100%; }
  .management-grid { grid-template-columns: 1fr; }
}
@media (max-width: 520px) {
  .workspace-actions :deep(.el-button) { margin-left: 0; }
  .workspace-copy h2 { font-size: 18px; }
  .workspace-summary small { display: none; }
}
</style>
