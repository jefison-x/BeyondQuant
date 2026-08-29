import { createRouter, createWebHistory } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import { legacySystemSettingsRouteName } from "./systemSettingsNavigation";

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
      path: "/admin/:section?",
      redirect: (to) => ({ name: legacySystemSettingsRouteName(to.params.section), query: to.query }),
      meta: { requiresAdmin: true },
    },
    {
      path: "/",
      component: () => import("@/components/layout/AppShell.vue"),
      children: [
        { path: "", redirect: "/agent" },
        {
          path: "dashboard",
          name: "dashboard",
          component: () => import("@/views/HomeView.vue"),
          meta: {
            title: "工作台",
            kicker: "账户主页",
            subtitle: "查看投研资产、最近回测、行情缓存和系统健康状态",
          },
        },
        {
          path: "settings/system",
          component: () => import("@/components/layout/SystemSettingsLayout.vue"),
          meta: { requiresAdmin: true, title: "系统设置", kicker: "管理员工作区", subtitle: "系统状态、数据、Agent 平台与审计" },
          children: [
            { path: "", redirect: "/settings/system/overview" },
            { path: "overview", name: "system-settings-overview", component: () => import("@/views/SystemOverviewView.vue") },
            { path: "plugins", name: "system-settings-plugins", component: () => import("@/views/PluginCenterView.vue") },
            { path: "data", name: "system-settings-data", component: () => import("@/views/DataCenterView.vue") },
            { path: "sources", name: "system-settings-sources", component: () => import("@/views/AdminOpsView.vue"), props: { section: "sources" } },
            { path: "cache", name: "system-settings-cache", component: () => import("@/views/AdminOpsView.vue"), props: { section: "cache" } },
            { path: "database", name: "system-settings-database", component: () => import("@/views/AdminOpsView.vue"), props: { section: "database" } },
            { path: "models", name: "system-settings-models", component: () => import("@/views/AdminOpsView.vue"), props: { section: "models" } },
            { path: "agents", name: "system-settings-agents", component: () => import("@/views/AdminOpsView.vue"), props: { section: "agents" } },
            { path: "budget", name: "system-settings-budget", component: () => import("@/views/AdminOpsView.vue"), props: { section: "budget" } },
            { path: "runtime", name: "system-settings-runtime", component: () => import("@/views/AdminOpsView.vue"), props: { section: "runtime" } },
            { path: "workflow", name: "system-settings-workflow", component: () => import("@/views/AdminOpsView.vue"), props: { section: "graphs" } },
            { path: "access", name: "system-settings-access", component: () => import("@/views/AdminOpsView.vue"), props: { section: "access" } },
            { path: "audit", name: "system-settings-audit", component: () => import("@/views/AdminOpsView.vue"), props: { section: "audit" } },
          ],
        },
        { path: "system-status", redirect: "/settings/system/overview", meta: { requiresAdmin: true } },
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
            subtitle: "管理可审阅的策略规则、版本与下一步回测",
          },
        },
        {
          path: "model-research",
          name: "model-research",
          component: () => import("@/views/MLResearchView.vue"),
          meta: {
            title: "模型研究",
            kicker: "量化模型工作台",
            subtitle: "训练可审计模型并生成样本外预测、冻结信号与可复现回测",
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
            kicker: "模拟交易工作台",
            subtitle: "管理纸面账户、T+1、结算与风控",
          },
        },
        {
          path: "user",
          component: () => import("@/components/layout/UserCenterLayout.vue"),
          children: [
            { path: "", redirect: "/user/profile" },
            { path: "profile", name: "user-profile", component: () => import("@/views/ProfileView.vue"), meta: { title: "个人资料", kicker: "用户中心", subtitle: "昵称、研究偏好与默认提示词" } },
            { path: "appearance", name: "user-appearance", component: () => import("@/views/AppearanceView.vue"), meta: { title: "外观与主题", kicker: "用户中心", subtitle: "跨设备显示模式和主题颜色" } },
            { path: "assets", name: "user-assets", component: () => import("@/views/AssetsView.vue"), meta: { title: "资产管理", kicker: "用户中心", subtitle: "资产清单与安全导入导出" } },
            { path: "paper-trading", redirect: (to) => ({ path: "/paper-trading", query: to.query, hash: to.hash }) },
            { path: "models", name: "user-models", component: () => import("@/views/ModelsView.vue"), meta: { title: "模型配置", kicker: "用户中心", subtitle: "写入保密凭据、模型档案和 Agent 绑定" } },
            { path: "agent-policy", name: "user-agent-policy", component: () => import("@/views/AgentPolicyView.vue"), meta: { title: "智能助手偏好", kicker: "用户中心", subtitle: "个人审批偏好和操作边界" } },
            { path: "research", name: "user-research", component: () => import("@/views/ResearchCenterView.vue"), meta: { title: "研究与审批", kicker: "用户中心", subtitle: "研究记录、策略版本与审批记录" } },
          ],
        },
        { path: "profile", redirect: "/user/profile" },
        { path: "assets", redirect: "/user/assets" },
        { path: "models", redirect: "/user/models" },
        { path: "agent-settings", redirect: "/user/agent-policy" },
        { path: "research-center", redirect: "/user/research" },
        { path: "data-center", redirect: "/settings/system/data", meta: { requiresAdmin: true } },
        { path: "operations", redirect: "/settings/system/overview", meta: { requiresAdmin: true } },
        {
          path: "quant",
          redirect: "/backtest",
        },
        {
          path: ":pathMatch(.*)*",
          name: "not-found",
          component: () => import("@/views/NotFoundView.vue"),
          meta: {
            title: "页面未找到",
            kicker: "导航提示",
            subtitle: "检查地址，或返回小巴投研工作台",
          },
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
  if (to.matched.some((record) => Boolean(record.meta.requiresAdmin)) && !auth.isAdmin) {
    return { name: "agent" };
  }
  if (to.name === "login" && auth.isAuthenticated) {
    return { name: "agent" };
  }
  return true;
});

export default router;
