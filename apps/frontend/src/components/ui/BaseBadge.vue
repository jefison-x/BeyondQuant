<script setup lang="ts">
defineProps<{ label: string; tone?: "info" | "success" | "warning" | "danger" }>();
</script>

<template>
  <span :class="['base-badge', tone ?? 'info']">{{ label }}</span>
</template>
