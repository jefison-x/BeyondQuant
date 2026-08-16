<script setup lang="ts">
defineProps<{ message?: string }>();
</script>

<template>
  <div class="base-empty">{{ message ?? "暂无数据" }}</div>
</template>
