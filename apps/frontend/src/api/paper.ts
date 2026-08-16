import type { PaperAccount, PaperOrder, StockPool } from "./types";

const ROOT = "/api/product/paper";

async function request<T>(path: string, token: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${ROOT}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      "content-type": "application/json",
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { error?: { message?: string }; detail?: string };
    throw new Error(body.error?.message ?? body.detail ?? "paper request failed");
  }
  return (await response.json()) as T;
}

export function createPaperAccount(name: string, cash: number, token: string): Promise<{ account: PaperAccount }> {
  return request("/accounts", token, { method: "POST", body: JSON.stringify({ name, cash }) });
}

export function getPaperAccount(accountId: string, token: string): Promise<{ account: PaperAccount }> {
  return request(`/accounts/${encodeURIComponent(accountId)}`, token);
}

export function createStockPool(
  name: string,
  symbols: string[],
  token: string,
): Promise<{ pool: StockPool }> {
  return request("/pools", token, { method: "POST", body: JSON.stringify({ name, symbols, provenance: { source: "frontend" } }) });
}

export function submitPaperOrder(
  payload: Record<string, unknown>,
  token: string,
): Promise<{ order: PaperOrder }> {
  return request("/orders", token, { method: "POST", body: JSON.stringify(payload) });
}

export function listPaperOrders(accountId: string, token: string): Promise<{ orders: PaperOrder[] }> {
  return request(`/accounts/${encodeURIComponent(accountId)}/orders`, token);
}
