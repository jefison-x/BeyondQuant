<script setup lang="ts">
const links = [
  { name: "dashboard", label: "首页", to: "/" },
  { name: "system-status", label: "状态", to: "/system-status" },
  { name: "agent", label: "研究", to: "/agent" },
];
</script>

<template>
  <nav class="app-bottom-nav">
    <RouterLink
      v-for="link in links"
      :key="link.name"
      :to="link.to"
      class="app-bottom-link"
      active-class="active"
    >
      {{ link.label }}
    </RouterLink>
  </nav>
</template>
