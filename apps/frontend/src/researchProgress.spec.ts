import { describe, expect, it } from "vitest";
import { researchProgress } from "./researchProgress";

describe("durable research progress", () => {
  it("never interprets missing or unknown checkpoints as completion", () => {
    expect(researchProgress(null).stage).toBe("尚未记录研究阶段");
    expect(researchProgress({ schema_version: "unknown", stage: "completed" }).stage).toBe("阶段信息待核对");
  });
  it("preserves the next action and blocker independently of model activity", () => {
    expect(researchProgress({ schema_version: "research-progress.v1", stage: "blocked",
      next_action: "核对原回测", blocked_reason: "结果尚未确认", completion_evidence: [] })).toEqual({
      stage: "需要处理阻塞", next: "核对原回测", blocker: "结果尚未确认", evidence: 0,
    });
  });
  it("labels completed as recorded evidence rather than guaranteed investment success", () => {
    expect(researchProgress({ schema_version: "research-progress.v1", stage: "completed",
      completion_evidence: ["artifact_original"] }).stage).toBe("已提交完成证据");
  });
});
