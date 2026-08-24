<script setup lang="ts">
withDefaults(defineProps<{ message?: string; retryLabel?: string; compact?: boolean }>(), {
  message: "加载失败",
  retryLabel: "重试",
  compact: false,
});

defineEmits<{ retry: [] }>();
</script>

<template>
  <div class="base-state base-error" :class="{ compact }" role="alert" aria-live="assertive">
    <span class="base-state__icon" aria-hidden="true">!</span>
    <strong>{{ message }}</strong>
    <small>数据没有被修改，可以安全重试。</small>
    <div class="base-state__actions">
      <slot name="actions">
        <el-button size="small" @click="$emit('retry')">{{ retryLabel }}</el-button>
      </slot>
    </div>
  </div>
</template>
