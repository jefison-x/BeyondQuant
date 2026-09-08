const STAGES: Record<string, string> = {
  planning: "制定方案", data_preparation: "准备数据", research: "研究分析", strategy: "编写策略",
  approval: "等待审批", training: "训练阶段", prediction: "预测阶段", backtest: "回测阶段",
  comparison: "比较结果", blocked: "需要处理阻塞", completed: "已提交完成证据",
};

export function researchProgress(value: unknown): { stage: string; next: string; blocker: string; evidence: number } {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return { stage: "尚未记录研究阶段", next: "请在原任务中核对进度", blocker: "", evidence: 0 };
  }
  const progress = value as Record<string, unknown>;
  if (progress.schema_version !== "research-progress.v1") {
    return { stage: "阶段信息待核对", next: "请核对原任务", blocker: "", evidence: 0 };
  }
  return {
    stage: typeof progress.stage === "string" ? STAGES[progress.stage] ?? "阶段信息待核对" : "阶段信息待核对",
    next: typeof progress.next_action === "string" ? progress.next_action : "无已登记的下一动作",
    blocker: typeof progress.blocked_reason === "string" ? progress.blocked_reason : "",
    evidence: Array.isArray(progress.completion_evidence) ? progress.completion_evidence.length : 0,
  };
}
