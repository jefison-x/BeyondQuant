<script setup lang="ts">
defineProps<{ label: string; value: string | number }>();
</script>

<template>
  <div class="metric-card">
    <span class="metric-label">{{ label }}</span>
    <strong class="metric-value">{{ value }}</strong>
  </div>
</template>
