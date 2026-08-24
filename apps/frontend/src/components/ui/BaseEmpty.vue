<script setup lang="ts">
withDefaults(defineProps<{ message?: string; description?: string; compact?: boolean }>(), {
  message: "暂无数据",
  description: "调整筛选条件或稍后刷新。",
  compact: false,
});
</script>

<template>
  <div class="base-state base-empty" :class="{ compact }" role="status">
    <span class="base-state__icon" aria-hidden="true">—</span>
    <strong>{{ message }}</strong>
    <small v-if="description">{{ description }}</small>
    <div v-if="$slots.actions" class="base-state__actions"><slot name="actions" /></div>
  </div>
</template>
