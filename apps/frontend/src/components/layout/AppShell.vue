<script setup lang="ts">
import AppHeader from "./AppHeader.vue";
import AppSidebar from "./AppSidebar.vue";
import AppBottomNav from "./AppBottomNav.vue";
</script>

<template>
  <div class="app-shell">
    <AppHeader />
    <div class="app-body">
      <AppSidebar />
      <main class="app-main">
        <RouterView />
      </main>
    </div>
    <AppBottomNav />
  </div>
</template>
