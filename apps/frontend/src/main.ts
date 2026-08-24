import { createPinia } from "pinia";
import { createApp } from "vue";
import ElementPlus from "element-plus";
import "element-plus/dist/index.css";
import App from "./App.vue";
import router from "./router";
import { useAuthStore } from "./stores/auth";
import { applyUiPreferences, readCachedUiPreferences, useAppearanceStore } from "./stores/appearance";
import "./styles/byq-theme.css";

async function bootstrap() {
  const app = createApp(App);
  const pinia = createPinia();
  app.use(pinia);
  const auth = useAuthStore();
  const appearance = useAppearanceStore();
  app.use(ElementPlus);

  // Resolve the durable session before installing the router so the auth
  // guard observes the authenticated principal instead of redirecting to
  // login during the initial navigation after a page refresh.
  try {
    await auth.fetchMe();
  } catch {
    auth.user = null;
  }
  if (auth.isAuthenticated) {
    try {
      await appearance.load();
    } catch {
      const cached = readCachedUiPreferences();
      if (cached) applyUiPreferences(cached);
    }
  } else {
    const cached = readCachedUiPreferences();
    if (cached) applyUiPreferences(cached);
  }

  app.use(router);
  await router.isReady();
  app.mount("#app");
}

void bootstrap();
