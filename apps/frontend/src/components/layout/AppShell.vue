<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRoute } from "vue-router";
import AppHeader from "./AppHeader.vue";
import AppSidebar from "./AppSidebar.vue";
import GlobalApprovalCenter from "@/components/agent/GlobalApprovalCenter.vue";
import XiaobaAssistantDrawer from "@/components/agent/XiaobaAssistantDrawer.vue";

const route = useRoute();
const isPublicRoute = computed(() => Boolean(route.meta.public));
const isMobile = ref(false);
const sidebarCollapsed = ref(false);
const mobileDrawerOpen = ref(false);

function updateViewport() {
  isMobile.value = window.innerWidth <= 767;
}

function toggleSidebarCollapse() {
  sidebarCollapsed.value = !sidebarCollapsed.value;
}

onMounted(() => {
  updateViewport();
  window.addEventListener("resize", updateViewport);
});

onUnmounted(() => {
  window.removeEventListener("resize", updateViewport);
});
</script>

<template>
  <div class="app-layout">
    <main v-if="isPublicRoute" class="public-area">
      <RouterView />
    </main>

    <template v-else>
      <div class="main-content">
        <AppSidebar
          v-if="!isMobile"
          :is-collapsed="sidebarCollapsed"
          @toggle-collapse="toggleSidebarCollapse"
        />
        <section class="workspace-shell">
          <AppHeader :show-menu="isMobile" @toggle-menu="mobileDrawerOpen = true" />
          <main class="content-area">
            <RouterView />
          </main>
        </section>
      </div>
      <el-drawer
        v-if="isMobile"
        v-model="mobileDrawerOpen"
        direction="ltr"
        :show-close="false"
        :with-header="false"
        size="min(86vw, 320px)"
        class="product-navigation-drawer"
        aria-label="产品导航"
      >
        <AppSidebar :is-collapsed="false" mobile @navigate="mobileDrawerOpen = false" />
      </el-drawer>
      <GlobalApprovalCenter />
      <XiaobaAssistantDrawer />
    </template>
  </div>
</template>

<style scoped>
.app-layout {
  background: var(--byq-bg);
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

.main-content {
  display: flex;
  flex: 1;
  height: 100vh;
  min-height: 0;
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

.public-area {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

@media (max-width: 767px) {
  .content-area {
    padding: 0.75rem;
  }
}

@media (min-width: 768px) and (max-width: 1199px) {
  .content-area {
    padding: 1rem;
  }
}

@media (min-width: 1200px) {
  .content-area {
    padding: 1.25rem;
  }
}
</style>

<style>
.product-navigation-drawer .el-drawer__body { padding: 0; }
</style>
