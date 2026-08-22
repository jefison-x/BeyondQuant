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
      path: "/admin",
      component: () => import("@/components/layout/OpsLayout.vue"),
      meta: { requiresAdmin: true },
      children: [
        { path: "", redirect: "/admin/database" },
        { path: "database", name: "admin-database", component: () => import("@/views/AdminOpsView.vue"), props: { section: "database" }, meta: { title: "数据库管理", kicker: "系统运维", subtitle: "数据库连接、迁移与底层结构状态" } },
        { path: "sources", name: "admin-sources", component: () => import("@/views/AdminOpsView.vue"), props: { section: "sources" }, meta: { title: "数据源管理", kicker: "系统运维", subtitle: "Tushare 配置就绪度与秘密安全状态" } },
        { path: "cache", name: "admin-cache", component: () => import("@/views/AdminOpsView.vue"), props: { section: "cache" }, meta: { title: "缓存管理", kicker: "系统运维", subtitle: "行情缓存覆盖、健康与重建" } },
        { path: "models", name: "admin-models", component: () => import("@/views/AdminOpsView.vue"), props: { section: "models" }, meta: { title: "模型运维", kicker: "系统运维", subtitle: "提供商、逻辑模型、密钥状态和 Agent 绑定" } },
        { path: "agents", name: "admin-agents", component: () => import("@/views/AdminOpsView.vue"), props: { section: "agents" }, meta: { title: "智能体运维", kicker: "系统运维", subtitle: "Agent 架构、技能配置与运行质量" } },
        { path: "budget", name: "admin-budget", component: () => import("@/views/AdminOpsView.vue"), props: { section: "budget" }, meta: { title: "执行预算", kicker: "系统运维", subtitle: "DSH 模型调用 token 记账与审计阈值" } },
        { path: "runtime", name: "admin-runtime", component: () => import("@/views/AdminOpsView.vue"), props: { section: "runtime" }, meta: { title: "运行诊断", kicker: "系统运维", subtitle: "runtime 健康、限制、使用量与错误分类" } },
        { path: "graphs", name: "admin-graphs", component: () => import("@/views/AdminOpsView.vue"), props: { section: "graphs" }, meta: { title: "Graph 工作流", kicker: "系统运维", subtitle: "BYQ AgentRun 与 WorkflowTrace 关联投影" } },
        { path: "access", name: "admin-access", component: () => import("@/views/AdminOpsView.vue"), props: { section: "access" }, meta: { title: "权限与审计", kicker: "系统运维", subtitle: "角色权限、审批策略和系统访问审计" } },
      ],
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
          path: "assets",
          name: "assets",
          component: () => import("@/views/AssetsView.vue"),
          meta: {
            title: "用户资产",
            kicker: "我的空间",
            subtitle: "策略、股票池、回测资产详情，支持导出与导入",
          },
        },
        {
          path: "models",
          name: "models",
          component: () => import("@/views/ModelsView.vue"),
          meta: {
            title: "模型设置",
            kicker: "个人模型",
            subtitle: "维护个人模型凭据、模型档案和 Agent 绑定",
          },
        },
        {
          path: "agent-settings",
          name: "agent-settings",
          component: () => import("@/views/AgentPolicyView.vue"),
          meta: {
            title: "智能体策略",
            kicker: "我的空间",
            subtitle: "配置个人审批偏好和智能体运行规则",
          },
        },
        {
          path: "profile",
          name: "profile",
          component: () => import("@/views/ProfileView.vue"),
          meta: {
            title: "个人设置",
            kicker: "个性化",
            subtitle: "设置用户昵称、研究偏好与默认提示词",
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
          redirect: "/admin/database",
          meta: {
            requiresAdmin: true,
            title: "系统运维",
            kicker: "系统运维",
            subtitle: "运行时、存储与可观测性状态",
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
  if (to.matched.some((record) => Boolean(record.meta.requiresAdmin)) && !auth.isAdmin) {
    return { name: "dashboard" };
  }
  if (to.name === "login" && auth.isAuthenticated) {
    return { name: "dashboard" };
  }
  return true;
});

export default router;
