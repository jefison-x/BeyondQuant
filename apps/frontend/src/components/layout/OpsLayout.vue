<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import AppHeader from "./AppHeader.vue";
import OpsSidebar from "./OpsSidebar.vue";

const isMobile = ref(false);
const collapsed = ref(false);
const mobileMenuOpen = ref(false);

function updateViewport() {
  isMobile.value = window.innerWidth <= 767;
}

onMounted(() => {
  updateViewport();
  window.addEventListener("resize", updateViewport);
});

onUnmounted(() => window.removeEventListener("resize", updateViewport));
</script>

<template>
  <div class="ops-layout">
    <OpsSidebar v-if="!isMobile" :is-collapsed="collapsed" @toggle-collapse="collapsed = !collapsed" />
    <el-drawer
      v-if="isMobile"
      v-model="mobileMenuOpen"
      class="ops-mobile-drawer"
      direction="ltr"
      :show-close="false"
      :with-header="false"
      size="280px"
    >
      <OpsSidebar
        :is-collapsed="false"
        @toggle-collapse="mobileMenuOpen = false"
        @navigate="mobileMenuOpen = false"
      />
    </el-drawer>
    <section class="workspace-shell">
      <AppHeader :show-menu="isMobile" @toggle-menu="mobileMenuOpen = true" />
      <main class="content-area">
        <RouterView />
      </main>
    </section>
  </div>
</template>

<style scoped>
.ops-layout {
  background: var(--byq-bg);
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.workspace-shell {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
}

.content-area {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 1rem;
}

:global(.ops-mobile-drawer .el-drawer__body) {
  padding: 0;
}

:global(.ops-mobile-drawer .ops-sidebar) {
  border-right: 0;
  width: 100%;
}
</style>
