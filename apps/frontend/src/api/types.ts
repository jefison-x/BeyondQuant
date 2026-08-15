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
