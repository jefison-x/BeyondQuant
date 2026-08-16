import { createPinia } from "pinia";
import { createApp } from "vue";
import ElementPlus from "element-plus";
import "element-plus/dist/index.css";
import App from "./App.vue";
import router from "./router";
import { useAuthStore } from "./stores/auth";
import "./styles/byq-theme.css";

const app = createApp(App);
app.use(createPinia());
const auth = useAuthStore();
app.use(router).use(ElementPlus);
auth.fetchMe()
  .catch(() => undefined)
  .finally(() => {
    router.isReady().then(() => app.mount("#app"));
  });
