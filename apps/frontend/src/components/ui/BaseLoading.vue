<script setup lang="ts">
withDefaults(defineProps<{ message?: string; compact?: boolean }>(), {
  message: "正在加载数据",
  compact: false,
});
</script>

<template>
  <div class="base-state base-loading" :class="{ compact }" role="status" aria-live="polite" aria-busy="true">
    <span class="base-state__spinner" aria-hidden="true" />
    <strong>{{ message }}</strong>
    <small>请稍候，当前内容会自动更新。</small>
  </div>
</template>
