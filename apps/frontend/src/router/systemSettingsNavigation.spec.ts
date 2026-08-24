import { describe, expect, it } from "vitest";
import {
  findSystemSettingsItem,
  legacySystemSettingsPath,
  legacySystemSettingsRouteName,
  systemSettingsGroups,
  systemSettingsItems,
} from "./systemSettingsNavigation";

describe("system settings navigation", () => {
  it("defines the closed Phase 45 administrator surface", () => {
    expect(systemSettingsGroups.map((group) => group.label)).toEqual([
      "系统",
      "数据平面",
      "Agent 平台",
      "安全与审计",
    ]);
    expect(systemSettingsItems.map((item) => item.path)).toEqual([
      "/settings/system/overview",
      "/settings/system/data",
      "/settings/system/sources",
      "/settings/system/cache",
      "/settings/system/database",
      "/settings/system/models",
      "/settings/system/agents",
      "/settings/system/budget",
      "/settings/system/runtime",
      "/settings/system/workflow",
      "/settings/system/access",
      "/settings/system/audit",
    ]);
  });

  it("preserves old administrator deep links through explicit redirects", () => {
    expect(legacySystemSettingsPath("database")).toBe("/settings/system/database");
    expect(legacySystemSettingsPath("graphs")).toBe("/settings/system/workflow");
    expect(legacySystemSettingsPath("unknown")).toBe("/settings/system/overview");
    expect(legacySystemSettingsRouteName("graphs")).toBe("system-settings-workflow");
    expect(findSystemSettingsItem("/settings/system/audit").label).toBe("审计记录");
  });
});
