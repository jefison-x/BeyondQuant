import type { Component } from "vue";
import {
  Coin,
  Connection,
  DataAnalysis,
  DataBoard,
  Files,
  Key,
  Lock,
  Money,
  Operation,
  SetUp,
  Share,
  Tools,
} from "@element-plus/icons-vue";

export interface SystemSettingsItem {
  path: string;
  label: string;
  description: string;
  icon: Component;
}

export interface SystemSettingsGroup {
  label: string;
  items: SystemSettingsItem[];
}

export const systemSettingsGroups: SystemSettingsGroup[] = [
  {
    label: "系统",
    items: [
      { path: "/settings/system/overview", label: "系统概览", description: "服务、存储与运行边界", icon: DataBoard },
    ],
  },
  {
    label: "数据平面",
    items: [
      { path: "/settings/system/data", label: "数据管理", description: "Tushare、同步与覆盖审计", icon: Files },
      { path: "/settings/system/sources", label: "数据源状态", description: "去敏配置就绪度", icon: Operation },
      { path: "/settings/system/cache", label: "缓存管理", description: "PostgreSQL 行情覆盖", icon: Coin },
      { path: "/settings/system/database", label: "数据库", description: "连接、版本与领域计数", icon: Connection },
    ],
  },
  {
    label: "Agent 平台",
    items: [
      { path: "/settings/system/models", label: "平台模型", description: "系统档案与绑定状态", icon: SetUp },
      { path: "/settings/system/agents", label: "Agent", description: "角色与最近运行", icon: Tools },
      { path: "/settings/system/budget", label: "执行预算", description: "有界阈值与用量", icon: Money },
      { path: "/settings/system/runtime", label: "运行时", description: "规范化 DSH 诊断", icon: DataAnalysis },
      { path: "/settings/system/workflow", label: "工作流诊断", description: "WorkflowTrace 关联", icon: Share },
    ],
  },
  {
    label: "安全与审计",
    items: [
      { path: "/settings/system/access", label: "访问控制", description: "持久用户与角色边界", icon: Lock },
      { path: "/settings/system/audit", label: "审计记录", description: "有界追加式记录", icon: Key },
    ],
  },
];

export const systemSettingsItems = systemSettingsGroups.flatMap((group) => group.items);

export function findSystemSettingsItem(path: string): SystemSettingsItem {
  return systemSettingsItems.find((item) => item.path === path) ?? systemSettingsItems[0];
}

const legacySections: Record<string, string> = {
  database: "database",
  sources: "sources",
  cache: "cache",
  models: "models",
  agents: "agents",
  budget: "budget",
  runtime: "runtime",
  graphs: "workflow",
  access: "access",
};

export function legacySystemSettingsPath(section?: string | string[]): string {
  const value = Array.isArray(section) ? section[0] : section;
  return `/settings/system/${legacySections[value ?? ""] ?? "overview"}`;
}

export function legacySystemSettingsRouteName(section?: string | string[]): string {
  const value = Array.isArray(section) ? section[0] : section;
  return `system-settings-${legacySections[value ?? ""] ?? "overview"}`;
}
