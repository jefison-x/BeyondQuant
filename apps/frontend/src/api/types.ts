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
  trace_id?: string;
  session_id?: string;
  sequence?: number;
  timestamp?: string;
  kind?: string;
  source?: string;
  payload?: Record<string, unknown>;
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
  models: Array<Record<string, unknown>>;
  credentials: { masked: boolean; write_only: boolean };
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
  approval_inbox: { pending: number };
}

export interface AssetImportReport {
  imported: { pools: number; paper_accounts: number };
  skipped: { strategies: number; backtests: number; reason: string };
  errors: Array<{ kind: string; message: string }>;
}

export interface PaperAccount {
  account_id?: string;
  name?: string;
  cash?: number;
  status?: string;
}

export interface StockPool {
  pool_id?: string;
  name?: string;
  pool_type?: string;
  description?: string;
  symbols?: string[];
  weights?: Record<string, number>;
  version?: string;
}

export interface PaperOrder {
  order_id?: string;
  symbol?: string;
  side?: "buy" | "sell";
  quantity?: number;
  price?: number;
  status?: "filled" | "blocked";
  blocked_reason?: string;
}

export interface PaperLedgerEntry {
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
