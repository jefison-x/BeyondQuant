export interface ProductError {
  error: {
    code: string;
    message: string;
    request_id: string;
  };
}

export interface ProductHealth {
  status: string;
  service: string;
}

export interface ProductDashboard {
  status: string;
  resources: {
    backend: string;
    data: string;
    migration: string;
    counts?: {
      tasks?: number | string;
      experiments?: number | string;
      artifacts?: number | string;
      backtests?: number | string;
    };
  };
}

export interface ProductDataStatus {
  status: string;
  provider: string;
  migration: string;
  backend: string;
}

export interface AgentSession {
  session_id: string;
  trace_id: string;
  status?: string;
}

export interface WorkflowTraceEvent {
  trace_id: string;
  session_id: string;
  sequence: number;
  timestamp: string;
  kind: string;
  source: "dsh" | "runtime-adapter" | "byq-domain";
  payload: Record<string, unknown>;
}

export type WorkflowCardKind =
  | "agent.card.strategy_draft"
  | "agent.card.stock_candidates"
  | "agent.card.optimization"
  | "agent.card.backtest_context"
  | "agent.card.approval";

export interface WorkflowCardCommon {
  [key: string]: unknown;
  schema_version: "workflow-card.v1";
  card_id: string;
  revision: number;
  authority: "proposal" | "domain";
  title: string;
  summary?: string;
  truncated: boolean;
}

export interface StrategyDraftCard extends WorkflowCardCommon {
  name: string;
  artifact_id?: string;
  strategy_id?: string;
  validation_status?: "unknown" | "draft" | "valid" | "invalid" | "superseded";
}

export interface StockCandidatesCard extends WorkflowCardCommon {
  items: Array<{ symbol: string; name?: string; reason?: string }>;
  as_of?: string;
  pool_id?: string;
}

export interface OptimizationCard extends WorkflowCardCommon {
  objective: string;
  changes: Array<{ area: string; before?: string; after: string; reason: string }>;
  strategy_artifact_id?: string;
  baseline_job_id?: string;
  metrics?: Record<string, number>;
}

export interface BacktestContextCard extends WorkflowCardCommon {
  authority: "domain";
  job_id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  metrics?: Record<string, number>;
  strategy_artifact_id?: string;
  result_artifact_id?: string;
}

export interface ApprovalCard extends WorkflowCardCommon {
  authority: "domain";
  approval_id: string;
  action: string;
  status: "pending" | "approved" | "rejected";
  execution_outcome: "not_started" | "authorized" | "not_authorized";
  risk_level?: "low" | "medium" | "high" | "critical";
  decided_by_display?: string;
}

export type WorkflowCardPayload =
  | StrategyDraftCard
  | StockCandidatesCard
  | OptimizationCard
  | BacktestContextCard
  | ApprovalCard;

type WorkflowCardEnvelope = Omit<WorkflowTraceEvent, "kind" | "payload">;
export type WorkflowCardEvent =
  | (WorkflowCardEnvelope & { kind: "agent.card.strategy_draft"; payload: StrategyDraftCard })
  | (WorkflowCardEnvelope & { kind: "agent.card.stock_candidates"; payload: StockCandidatesCard })
  | (WorkflowCardEnvelope & { kind: "agent.card.optimization"; payload: OptimizationCard })
  | (WorkflowCardEnvelope & { kind: "agent.card.backtest_context"; payload: BacktestContextCard })
  | (WorkflowCardEnvelope & { kind: "agent.card.approval"; payload: ApprovalCard });

export interface WorkflowActivityPayload {
  schema_version: "workflow-activity.v1";
  activity_id: string;
  phase: "understand" | "select" | "strategy" | "backtest" | "review" | "tool";
  state: "started" | "progress" | "completed" | "failed" | "waiting_approval";
  label: string;
  capability?: string;
}

export interface BacktestJob {
  job_id?: string;
  status?: string;
  summary?: Record<string, unknown>;
  input_manifest?: Record<string, unknown>;
  attempts?: number;
  max_attempts?: number;
  error_code?: string;
  error_message?: string;
  strategy_version_artifact_id?: string;
  approval_artifact_id?: string;
  result_artifact_id?: string;
}

export interface BacktestEquityPoint {
  trade_date: string;
  equity: number;
  cash: number;
  positions_count: number;
}

export interface BacktestResult {
  schema_version?: string;
  engine?: string;
  final_value?: number;
  total_return?: number;
  max_drawdown?: number;
  trade_count?: number;
  blocked_trade_count?: number;
  trades?: Array<Record<string, unknown>>;
  blocked_trades?: Array<Record<string, unknown>>;
  corporate_action_events?: Array<Record<string, unknown>>;
  equity_curve?: BacktestEquityPoint[];
  daily_positions?: Array<Record<string, unknown>>;
  daily_returns?: Array<Record<string, unknown>>;
  logs?: Array<Record<string, unknown>>;
  log_truncated?: boolean;
  strategy_version_artifact_id?: string;
  approval_artifact_id?: string;
  reproducibility?: string;
}

export interface SettingsStatus {
  profile: { configured: boolean };
  model_provider: { configured: boolean };
  data_provider: { provider: string; migration: string };
  storage: { status: string };
  approval_inbox: { pending: number };
}

export interface UserProfile {
  subject: string;
  display_name: string;
  preferences: string;
  default_prompt: string;
  role: string;
  status: string;
}

export interface ModelSettings {
  provider: string;
  configured: boolean;
  models: Array<{ provider: string; model: string; display_name: string; reasoning_supported: boolean }>;
  agents: Array<{ agent_id: string; name: string }>;
  credential_items: ModelCredential[];
  profiles: ModelProfile[];
  bindings: ModelBinding[];
  audit: Array<Record<string, unknown>>;
  encryption: { configured: boolean; status: string; envelope_version?: string };
  credentials: { masked: boolean; write_only: boolean };
}

export interface ModelCredential {
  credential_id: string;
  provider: string;
  label: string;
  status: "active" | "disabled" | "revoked";
  configured: boolean;
  masked: string;
  version: number;
  updated_at: string;
}

export interface ModelProfile {
  profile_id: string;
  credential_id: string;
  key_name: string;
  display_name: string;
  provider: string;
  model: string;
  temperature: number;
  reasoning_enabled: boolean;
  status: string;
  available: boolean;
  version: number;
}

export interface ModelBinding {
  agent_id: string;
  agent_name: string;
  profile_id: string | null;
  profile_name?: string | null;
  model?: string | null;
  effective_source: "personal" | "system_default";
  available: boolean;
  version: number;
}

export interface AssetSummary {
  strategies: Array<Record<string, unknown>>;
  backtests: Array<Record<string, unknown>>;
  pools: Array<Record<string, unknown>>;
  paper_accounts: Array<Record<string, unknown>>;
  summary: {
    strategies: number;
    backtests: number;
    pools: number;
    paper_accounts: number;
  };
}

export interface AgentPolicyStatus {
  platform_policy: {
    automation_enabled: boolean;
    paused: boolean;
    default_decision_mode: string;
    max_auto_executions_per_hour: number;
    max_auto_failures_per_hour: number;
  };
  personal_policy: {
    owner_principal?: string;
    automation_enabled: boolean;
    paused: boolean;
    default_decision_mode: string;
    max_auto_executions_per_hour: number;
    max_auto_failures_per_hour: number;
  };
  rules: AgentPolicyRule[];
  presets: AgentPolicyPreset[];
  audit: Array<Record<string, unknown>>;
  approval_inbox: { pending: number };
}

export interface AgentPolicyRule {
  rule_id: string;
  name: string;
  description: string;
  action: string;
  agent_id: string;
  decision_mode: string;
  risk_level: string;
  priority: number;
  enabled: boolean;
  version: number;
}

export interface AgentPolicyPreset {
  preset_id: string;
  name: string;
  description: string;
  rules: Array<Record<string, unknown>>;
}

export interface AssetImportReport {
  imported: { strategies: number; backtests: number; pools: number; paper_accounts: number };
  source_owner_reused: false;
  identity_policy: string;
  errors: Array<{ kind: string; message: string }>;
}

export interface PaperAccount {
  account_id?: string;
  name?: string;
  cash?: number;
  initial_cash?: number;
  equity?: number;
  realized_pnl?: number;
  currency?: string;
  status?: string;
  version?: number;
  last_settlement_date?: string | null;
  bound_pool_id?: string | null;
  bound_snapshot_id?: string | null;
}

export interface StockPool {
  pool_id?: string;
  name?: string;
  pool_type?: string;
  description?: string;
  symbols?: string[];
  weights?: Record<string, number>;
  version?: string;
  status?: "active" | "inactive" | "deleted";
  current_snapshot_id?: string;
  metadata_version?: number;
  member_count?: number;
  snapshot?: StockPoolSnapshot;
  provenance?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

export interface StockPoolSnapshot {
  snapshot_id: string;
  pool_id: string;
  version_number: number;
  membership_fingerprint: string;
  snapshot_fingerprint: string;
  definition: Record<string, unknown>;
  provenance: Record<string, unknown>;
  effective_trade_date?: string | null;
  weight_mode: "weighted" | "unweighted";
  weight_sum?: string | null;
  member_count: number;
  members?: Array<{ symbol: string; weight: string | null }>;
  created_at: string;
}

export interface PaperOrder {
  order_id?: string;
  symbol?: string;
  side?: "buy" | "sell";
  quantity?: number;
  price?: number;
  status?: "filled" | "blocked";
  blocked_reason?: string;
  trade_date?: string;
  fees?: number;
  tax?: number;
  cash_delta?: number;
  pool_id?: string;
  stock_pool_snapshot_id?: string;
  risk_evaluation_json?: Record<string, unknown>;
  decision_provenance_json?: Record<string, unknown>;
  events_json?: Array<Record<string, unknown>>;
  fill?: Record<string, unknown> | null;
}

export interface PaperLedgerEntry {
  entry_id?: string;
  entry_type?: string;
  fill_id?: string;
  trade_date?: string;
  symbol?: string;
  side?: "buy" | "sell";
  quantity?: number;
  price?: number;
  amount?: number;
  fees?: number;
  cash_delta?: number;
  realized_pnl?: number;
  created_at?: string;
}

export interface PaperSnapshot {
  snapshot_id: string;
  trade_date: string;
  cash: number;
  market_value: number;
  equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  daily_pnl: number;
  daily_return?: number | null;
  positions_json: Array<Record<string, unknown>>;
  snapshot_fingerprint: string;
}

export interface PaperControls {
  kill_switch_engaged: boolean;
  kill_switch_reason?: string | null;
  max_order_notional?: number | null;
  version: number;
  updated_at?: string;
}

export interface OperationsStatus {
  backend: string;
  runtime: string;
  storage: string;
  migration: string;
  observability: { workflow_trace: string; audit: string };
}

export interface DataCenterStatus {
  migration: string;
  datasets: Array<Record<string, unknown>>;
  provider: string;
  quality: string;
  provider_status: {
    configured: boolean;
    sync: string;
  };
}
