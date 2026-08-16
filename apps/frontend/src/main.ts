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
await auth.fetchMe().catch(() => undefined);
app.use(router).use(ElementPlus);
await router.isReady();
app.mount("#app");
