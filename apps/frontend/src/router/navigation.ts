import type { Component } from "vue";
import {
  Bell,
  ChatLineRound,
  Coin,
  DataAnalysis,
  FolderOpened,
  Histogram,
  HomeFilled,
  Management,
  Monitor,
  SetUp,
  Tools,
} from "@element-plus/icons-vue";

export interface NavItem {
  to: string;
  label: string;
  icon: Component;
}

export interface NavGroup {
  index: string;
  label: string;
  icon: Component;
  items: NavItem[];
}

export const businessNavGroups: NavGroup[] = [
  {
    index: "research-workbench",
    label: "投研工作台",
    icon: HomeFilled,
    items: [
      { to: "/", label: "工作台", icon: HomeFilled },
      { to: "/agent", label: "小巴投研", icon: ChatLineRound },
    ],
  },
  {
    index: "research-strategy",
    label: "研究与策略",
    icon: Management,
    items: [
      { to: "/stock-pool", label: "股票管理", icon: FolderOpened },
      { to: "/strategy", label: "策略管理", icon: Management },
    ],
  },
  {
    index: "research-execution",
    label: "验证与执行",
    icon: DataAnalysis,
    items: [
      { to: "/backtest", label: "回测管理", icon: Histogram },
      { to: "/paper-trading", label: "模拟操盘", icon: DataAnalysis },
    ],
  },
  {
    index: "my-space",
    label: "我的空间",
    icon: FolderOpened,
    items: [
      { to: "/assets", label: "用户资产", icon: FolderOpened },
      { to: "/models", label: "个人模型", icon: SetUp },
      { to: "/agent-settings", label: "智能体策略", icon: SetUp },
      { to: "/profile", label: "个人设置", icon: SetUp },
      { to: "/research-center", label: "研究/审批", icon: Bell },
    ],
  },
  {
    index: "system-operations",
    label: "系统",
    icon: Tools,
    items: [
      { to: "/data-center", label: "数据中心", icon: Coin },
      { to: "/system-status", label: "系统状态", icon: Monitor },
    ],
  },
];

export function findActiveNavItem(path: string): string {
  if (path === "/") return "/";
  return businessNavGroups.flatMap((group) => group.items).find((item) => item.to === path)?.to ?? "";
}
