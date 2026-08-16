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
  resources: Record<string, string>;
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
}

export interface SettingsStatus {
  profile: { configured: boolean };
  model_provider: { configured: boolean };
  data_provider: { provider: string; migration: string };
  storage: { status: string };
  approval_inbox: { pending: number };
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
  symbols?: string[];
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
}
