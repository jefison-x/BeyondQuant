import type { Component } from "vue";
import { Collection, DataAnalysis, Histogram, Management } from "@element-plus/icons-vue";

export interface NavItem {
  to: string;
  label: string;
  icon: Component;
}

/** ADR-0024 keeps the primary Product information architecture flat. */
export const primaryNavItems: NavItem[] = [
  { to: "/stock-pool", label: "股票池管理", icon: Collection },
  { to: "/strategy", label: "策略管理", icon: Management },
  { to: "/backtest", label: "回测管理", icon: Histogram },
];

export const historyNavItem: NavItem = {
  to: "/agent",
  label: "历史会话",
  icon: DataAnalysis,
};

export function findActiveNavItem(path: string): string {
  return primaryNavItems.find((item) => item.to === path)?.to ?? (path === "/agent" ? "/agent" : "");
}
