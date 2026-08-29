<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { listAgentSessions } from "@/api/agent";
import { useAgentStore } from "@/stores/agent";
import { useAuthStore } from "@/stores/auth";
import AppHeader from "./AppHeader.vue";
import AppSidebar from "./AppSidebar.vue";

const route = useRoute();
const agent = useAgentStore();
const auth = useAuthStore();
const isPublicRoute = computed(() => Boolean(route.meta.public));
const isConversationRoute = computed(() => route.path === "/agent");
const isSystemSettingsRoute = computed(() => route.path.startsWith("/settings/system"));
const isMobile = ref(false);
const sidebarCollapsed = ref(false);
const mobileDrawerOpen = ref(false);
const contentArea = ref<HTMLElement | null>(null);

function updateViewport() {
  isMobile.value = window.innerWidth <= 767;
}

function toggleSidebarCollapse() {
  sidebarCollapsed.value = !sidebarCollapsed.value;
}

onMounted(async () => {
  updateViewport();
  window.addEventListener("resize", updateViewport);
  if (!isPublicRoute.value && auth.isAuthenticated) {
    try {
      const response = await listAgentSessions(auth.token, { limit: 100 });
      agent.replaceSessions(response.sessions);
    } catch {
      // The shell remains usable when the best-effort recent catalogue is unavailable.
    }
  }
});

onUnmounted(() => {
  window.removeEventListener("resize", updateViewport);
});

watch(() => route.fullPath, async () => {
  await nextTick();
  // Lazy route chunks and data-backed views do not always mount in the first
  // post-navigation frame. Keep the focus target aligned with the latest
  // heading while the transition settles instead of leaving focus in the
  // sidebar button that initiated navigation.
  for (let attempt = 0; attempt < 12; attempt += 1) {
    await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
    const heading = contentArea.value?.querySelector<HTMLElement>("h1, h2");
    if (!heading) continue;
    heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
  }
}, { flush: "post", immediate: true });
</script>

<template>
  <div class="app-layout">
    <main v-if="isPublicRoute" class="public-area">
      <RouterView />
    </main>

    <template v-else>
      <div
        class="main-content"
        :inert="isSystemSettingsRoute"
        :aria-hidden="isSystemSettingsRoute ? 'true' : undefined"
      >
        <AppSidebar
          v-if="!isMobile"
          :is-collapsed="sidebarCollapsed"
          @toggle-collapse="toggleSidebarCollapse"
        />
        <section class="workspace-shell">
          <AppHeader :show-menu="isMobile" @toggle-menu="mobileDrawerOpen = true" />
          <main ref="contentArea" class="content-area" :class="{ 'content-area--conversation': isConversationRoute }" tabindex="-1">
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

.content-area.content-area--conversation {
  overflow: hidden;
  padding: 0;
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
