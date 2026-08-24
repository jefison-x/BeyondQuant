import { describe, expect, it } from "vitest";
import { findActiveNavItem, primaryNavItems } from "./navigation";

describe("conversation-first navigation", () => {
  it("keeps exactly three route destinations beside the two conversation actions", () => {
    expect(primaryNavItems.map((item) => [item.to, item.label])).toEqual([
      ["/stock-pool", "股票池管理"],
      ["/strategy", "策略管理"],
      ["/backtest", "回测管理"],
    ]);
  });

  it("does not mark relocated account or operations routes as primary", () => {
    expect(findActiveNavItem("/agent")).toBe("/agent");
    expect(findActiveNavItem("/assets")).toBe("");
    expect(findActiveNavItem("/admin/database")).toBe("");
    expect(findActiveNavItem("/settings/system/overview")).toBe("");
  });
});
