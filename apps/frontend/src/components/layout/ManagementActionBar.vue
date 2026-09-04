<script setup lang="ts">
withDefaults(defineProps<{
  title?: string;
  description: string;
}>(), {
  title: "管理操作",
});
</script>

<template>
  <section class="management-action-bar" aria-label="管理操作" data-testid="management-action-bar">
    <div class="management-action-copy">
      <div class="management-action-title">
        <strong>{{ title }}</strong>
        <slot name="status" />
      </div>
      <p>{{ description }}</p>
    </div>
    <div v-if="$slots.default" class="management-action-buttons">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.management-action-bar {
  align-items: center;
  background: var(--byq-surface-subtle);
  border: 1px solid var(--byq-border-subtle);
  border-radius: var(--byq-radius-sm);
  display: flex;
  gap: 14px;
  justify-content: space-between;
  margin-bottom: 14px;
  padding: 10px 12px;
}
.management-action-copy { display: grid; gap: 3px; min-width: 0; }
.management-action-title { align-items: center; display: flex; flex-wrap: wrap; gap: 7px; }
.management-action-title strong { color: var(--byq-text); font-size: 12px; }
.management-action-copy p { color: var(--byq-text-muted); font-size: 11px; line-height: 1.5; margin: 0; }
.management-action-buttons { align-items: center; display: flex; flex: 0 0 auto; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
.management-action-buttons :deep(.el-button) { margin-left: 0; }
@media (max-width: 640px) {
  .management-action-bar { align-items: stretch; flex-direction: column; }
  .management-action-buttons { justify-content: flex-start; }
}
</style>
