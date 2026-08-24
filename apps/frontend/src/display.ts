const STATUS_LABELS: Record<string, string> = {
  active: "启用",
  inactive: "停用",
  draft: "草稿",
  validated: "已验证",
  approved: "已批准",
  denied: "已拒绝",
  pending: "待处理",
  queued: "排队中",
  running: "运行中",
  completed: "已完成",
  cancelled: "已取消",
  failed: "失败",
  superseded: "已归档",
  unknown: "未知",
};

export function statusLabel(value: unknown): string {
  const normalized = String(value ?? "unknown").trim().toLowerCase();
  return STATUS_LABELS[normalized] ?? String(value ?? "-");
}

export function formatCount(value: unknown): string {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString("zh-CN") : "-";
}
