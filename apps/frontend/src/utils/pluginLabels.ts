const STATUS_LABELS: Record<string, string> = {
  AVAILABLE: "可用候选",
  QUALIFIED: "已通过资格认证",
  ENABLED: "已启用",
  BLOCKED: "已阻止",
  REJECTED: "已拒绝",
  DEPRECATED: "已弃用",
  ACTIVE: "运行中",
  DESIRED: "待部署",
  validated: "已验证",
  queued: "排队中",
  succeeded: "已成功",
  completed: "已完成",
  failed: "失败",
  awaiting_generation: "等待生成组合",
  generated: "组合已生成",
  deploying: "部署中",
  active: "运行中",
  rolled_back: "已回滚",
  not_applicable: "不适用",
};

const RISK_LABELS: Record<string, string> = {
  LOW: "低风险",
  MEDIUM: "中风险",
  HIGH: "高风险",
  PROHIBITED: "禁止使用",
};

const COMPATIBILITY_LABELS: Record<string, string> = {
  COMPATIBLE: "与当前运行时兼容",
  BLOCKED_BY_RUNTIME_VERSION: "受当前运行时版本限制",
  BLOCKED_BY_SECURITY_BOUNDARY: "受产品安全边界限制",
};

const CAPABILITY_LABELS: Record<string, string> = {
  network: "网络访问",
  web_search: "网页搜索",
  web_fetch: "网页抓取",
  filesystem_read: "文件系统读取",
  filesystem_write: "文件系统写入",
  shell: "Shell 命令",
  terminal: "终端访问",
  code_execution: "代码执行",
  git: "Git 操作",
  database: "数据库访问",
  subprocess: "子进程",
  persistent_storage: "持久化存储",
  runtime_mutation: "运行时修改",
  user_interaction: "用户交互",
};

const AGENT_LABELS: Record<string, string> = {
  quant_orchestrator: "量化协调 Agent",
  market_researcher: "市场研究 Agent",
  factor_researcher: "因子研究 Agent",
  strategy_researcher: "策略研究 Agent",
  backtest_analyst: "回测分析 Agent",
};

const ACTION_LABELS: Record<string, string> = {
  enable: "启用",
  disable: "停用",
  assign: "修改 Agent 授权",
  qualify: "资格认证",
};

export const pluginStatusLabel = (value: string) => STATUS_LABELS[value] ?? value;
export const pluginRiskLabel = (value: string) => RISK_LABELS[value] ?? value;
export const pluginCompatibilityLabel = (value: string) => COMPATIBILITY_LABELS[value] ?? value;
export const pluginCapabilityLabel = (value: string) => CAPABILITY_LABELS[value] ?? value;
export const pluginAgentLabel = (value: string) => AGENT_LABELS[value] ?? value;
export const pluginActionLabel = (value: string) => ACTION_LABELS[value] ?? value;
