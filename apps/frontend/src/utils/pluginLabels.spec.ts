import { describe, expect, it } from "vitest";
import {
  pluginActionLabel,
  pluginAgentLabel,
  pluginCapabilityLabel,
  pluginCompatibilityLabel,
  pluginRiskLabel,
  pluginStatusLabel,
} from "./pluginLabels";

describe("Plugin Center 中文文案", () => {
  it("将产品状态、风险和兼容性枚举转成中文", () => {
    expect(pluginStatusLabel("QUALIFIED")).toBe("已通过资格认证");
    expect(pluginStatusLabel("awaiting_generation")).toBe("等待生成组合");
    expect(pluginRiskLabel("HIGH")).toBe("高风险");
    expect(pluginCompatibilityLabel("BLOCKED_BY_SECURITY_BOUNDARY")).toBe("受产品安全边界限制");
  });

  it("将能力、Agent 和治理动作转成中文但保留未知技术标识", () => {
    expect(pluginCapabilityLabel("web_search")).toBe("网页搜索");
    expect(pluginAgentLabel("market_researcher")).toBe("市场研究 Agent");
    expect(pluginActionLabel("qualify")).toBe("资格认证");
    expect(pluginCapabilityLabel("future_capability")).toBe("future_capability");
  });
});
