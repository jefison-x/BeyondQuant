import { createRouter, createWebHistory } from "vue-router";
import { useAuthStore } from "@/stores/auth";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/login",
      name: "login",
      component: () => import("@/views/LoginView.vue"),
      meta: { public: true },
    },
    {
      path: "/",
      component: () => import("@/components/layout/AppShell.vue"),
      children: [
        {
          path: "",
          name: "dashboard",
          component: () => import("@/views/HomeView.vue"),
          meta: {
            title: "工作台",
            kicker: "账户主页",
            subtitle: "查看投研资产、最近回测、行情缓存和系统健康状态",
          },
        },
        {
          path: "system-status",
          name: "system-status",
          component: () => import("@/views/SystemStatusView.vue"),
          meta: {
            title: "系统状态",
            kicker: "系统运维",
            subtitle: "核心服务健康状态与可观测性",
          },
        },
        {
          path: "agent",
          name: "agent",
          component: () => import("@/views/AgentView.vue"),
          meta: {
            title: "小巴投研",
            kicker: "量化研究工作台",
            subtitle: "在一个连续会话中推进选股、策略、回测与复盘",
          },
        },
        {
          path: "stock-pool",
          name: "stock-pool",
          component: () => import("@/views/StockPoolView.vue"),
          meta: {
            title: "股票管理",
            kicker: "股票池工作台",
            subtitle: "管理研究股票池和成分清单",
          },
        },
        {
          path: "strategy",
          name: "strategy",
          component: () => import("@/views/StrategyView.vue"),
          meta: {
            title: "策略管理",
            kicker: "策略工作台",
            subtitle: "管理和生成 Python 策略",
          },
        },
        {
          path: "backtest",
          name: "backtest",
          component: () => import("@/views/BacktestView.vue"),
          meta: {
            title: "回测管理",
            kicker: "回测任务中心",
            subtitle: "验证策略表现和成交假设",
          },
        },
        {
          path: "paper-trading",
          name: "paper-trading",
          component: () => import("@/views/PaperTradingView.vue"),
          meta: {
            title: "模拟操盘",
            kicker: "模拟操盘",
            subtitle: "纸面账户、T+1 可卖数量、风控开关和策略收益",
          },
        },
        {
          path: "settings",
          name: "settings",
          component: () => import("@/views/SettingsView.vue"),
          meta: {
            title: "个人设置",
            kicker: "我的空间",
            subtitle: "用户与平台设置",
          },
        },
        {
          path: "research-center",
          name: "research-center",
          component: () => import("@/views/ResearchCenterView.vue"),
          meta: {
            title: "研究/审批",
            kicker: "我的空间",
            subtitle: "研究实体与审批记录",
          },
        },
        {
          path: "data-center",
          name: "data-center",
          component: () => import("@/views/DataCenterView.vue"),
          meta: {
            title: "数据中心",
            kicker: "系统运维",
            subtitle: "行情数据迁移、提供方与质量状态",
          },
        },
        {
          path: "operations",
          name: "operations",
          component: () => import("@/views/OperationsView.vue"),
          meta: {
            title: "系统运维",
            kicker: "系统运维",
            subtitle: "运行时、存储与可观测性状态",
          },
        },
        {
          path: "admin",
          name: "admin",
          component: () => import("@/views/AdminView.vue"),
          meta: {
            title: "管理",
            kicker: "系统运维",
            subtitle: "用户与平台管理",
          },
        },
        {
          path: "quant",
          redirect: "/backtest",
        },
      ],
    },
  ],
});

router.beforeEach((to) => {
  const auth = useAuthStore();
  if (!to.meta.public && !auth.isAuthenticated) {
    return { name: "login", query: { redirect: to.fullPath } };
  }
  if (to.name === "login" && auth.isAuthenticated) {
    return { name: "dashboard" };
  }
  return true;
});

export default router;
