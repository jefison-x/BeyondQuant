import type { ProductDashboard, ProductDataStatus, ProductHealth } from "./types";

const API_ROOT = "/api/product";

export class ProductApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string, token: string): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, {
    credentials: "include",
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as Partial<{ error: { code?: string; message?: string } }>;
    throw new ProductApiError(
      response.status,
      body.error?.code ?? "request_failed",
      body.error?.message ?? "request failed",
    );
  }
  return (await response.json()) as T;
}

export function fetchHealth(token: string): Promise<ProductHealth> {
  return request<ProductHealth>("/health", token);
}

export function fetchDashboard(token: string): Promise<ProductDashboard> {
  return request<ProductDashboard>("/dashboard", token);
}

export function fetchDataStatus(token: string): Promise<ProductDataStatus> {
  return request<ProductDataStatus>("/data/status", token);
}
