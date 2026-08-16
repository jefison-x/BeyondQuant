<script setup lang="ts">
defineProps<{ title?: string }>();
</script>

<template>
  <section class="base-card">
    <header v-if="title" class="base-card-header">
      <h3>{{ title }}</h3>
    </header>
    <div class="base-card-body">
      <slot />
    </div>
  </section>
</template>
