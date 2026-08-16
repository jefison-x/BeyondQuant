<script setup lang="ts">
defineProps<{ message?: string }>();
</script>

<template>
  <div class="base-error" role="alert">{{ message ?? "加载失败" }}</div>
</template>
