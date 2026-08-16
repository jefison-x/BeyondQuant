import { createRouter, createWebHistory } from "vue-router";
import { useAuthStore } from "@/stores/auth";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/login",
      name: "login",
      component: () => import("@/views/LoginView.vue"),
    },
    {
      path: "/",
      component: () => import("@/components/layout/AppShell.vue"),
      children: [
        {
          path: "",
          name: "dashboard",
          component: () => import("@/views/HomeView.vue"),
        },
        {
          path: "system-status",
          name: "system-status",
          component: () => import("@/views/SystemStatusView.vue"),
        },
        {
          path: "agent",
          name: "agent",
          component: () => import("@/views/AgentView.vue"),
        },
        {
          path: "quant",
          name: "quant",
          component: () => import("@/views/QuantWorkspaceView.vue"),
        },
        {
          path: "settings",
          name: "settings",
          component: () => import("@/views/SettingsView.vue"),
        },
        {
          path: "stock-pool",
          name: "stock-pool",
          component: () => import("@/views/StockPoolView.vue"),
        },
        {
          path: "paper-trading",
          name: "paper-trading",
          component: () => import("@/views/PaperTradingView.vue"),
        },
        {
          path: "operations",
          name: "operations",
          component: () => import("@/views/OperationsView.vue"),
        },
        {
          path: "research-center",
          name: "research-center",
          component: () => import("@/views/ResearchCenterView.vue"),
        },
      ],
    },
  ],
});

router.beforeEach((to) => {
  const auth = useAuthStore();
  if (to.name !== "login" && !auth.isAuthenticated) {
    return { name: "login", query: { redirect: to.fullPath } };
  }
  if (to.name === "login" && auth.isAuthenticated) {
    return { name: "dashboard" };
  }
  return true;
});

export default router;
