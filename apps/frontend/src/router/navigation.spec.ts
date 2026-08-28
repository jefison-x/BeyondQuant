import { describe, expect, it } from "vitest";
import { findActiveNavItem, primaryNavItems } from "./navigation";

describe("conversation-first navigation", () => {
  it("keeps the four business workspaces in their product order", () => {
    expect(primaryNavItems.map((item) => [item.to, item.label])).toEqual([
      ["/stock-pool", "股票池管理"],
      ["/strategy", "策略管理"],
      ["/backtest", "回测管理"],
      ["/paper-trading", "模拟操盘"],
    ]);
  });

  it("does not mark relocated account or operations routes as primary", () => {
    expect(findActiveNavItem("/agent")).toBe("/agent");
    expect(findActiveNavItem("/paper-trading")).toBe("/paper-trading");
    expect(findActiveNavItem("/user/paper-trading")).toBe("");
    expect(findActiveNavItem("/assets")).toBe("");
    expect(findActiveNavItem("/admin/database")).toBe("");
    expect(findActiveNavItem("/settings/system/overview")).toBe("");
  });
});
