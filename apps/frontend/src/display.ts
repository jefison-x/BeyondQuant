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
  starting: "正在启动",
  cancelling: "正在停止",
  interrupted: "已停止",
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

const BACKTEST_METRIC_LABELS: Record<string, string> = {
  total_return: "累计收益",
  benchmark_return: "基准收益",
  excess_return: "超额收益",
  max_drawdown: "最大回撤",
  trade_count: "成交笔数",
  blocked_trade_count: "被拦截交易",
  final_value: "期末资产",
};

export function backtestMetricLabel(value: string): string {
  return BACKTEST_METRIC_LABELS[value] ?? "其他指标";
}

export function shortReference(value: unknown): string {
  const normalized = String(value ?? "").trim();
  if (!normalized) return "-";
  return normalized.length <= 12 ? normalized : `${normalized.slice(0, 8)}…${normalized.slice(-4)}`;
}
