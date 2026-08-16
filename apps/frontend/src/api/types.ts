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
