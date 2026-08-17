import type { PaperAccount, PaperLedgerEntry, PaperOrder, StockPool } from "./types";

const ROOT = "/api/product/paper";

async function request<T>(path: string, token: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${ROOT}${path}`, {
    ...init,
    credentials: "include",
    headers: {
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

export function listPaperAccounts(token: string): Promise<{ accounts: Array<Record<string, unknown>> }> {
  return request(`/accounts`, token);
}

export function createStockPool(
  name: string,
  symbols: string[],
  token: string,
  options: { poolType?: string; description?: string; weights?: Record<string, number> } = {},
): Promise<{ pool: StockPool }> {
  return request("/pools", token, {
    method: "POST",
    body: JSON.stringify({
      name,
      symbols,
      provenance: { source: "frontend" },
      pool_type: options.poolType ?? "custom",
      description: options.description ?? null,
      weights: options.weights ?? {},
    }),
  });
}

export function listStockPools(token: string): Promise<{ pools: Array<Record<string, unknown>> }> {
  return request(`/pools`, token);
}

export function submitPaperOrder(
  payload: Record<string, unknown>,
  token: string,
): Promise<{ order: PaperOrder }> {
  return request("/orders", token, { method: "POST", body: JSON.stringify(payload) });
}

export function listPaperPositions(accountId: string, token: string): Promise<{ positions: Array<Record<string, unknown>> }> {
  return request(`/accounts/${encodeURIComponent(accountId)}/positions`, token);
}

export function listPaperFills(accountId: string, token: string): Promise<{ fills: Array<Record<string, unknown>> }> {
  return request(`/accounts/${encodeURIComponent(accountId)}/fills`, token);
}

export function listPaperLedger(accountId: string, token: string): Promise<{ ledger: PaperLedgerEntry[] }> {
  return request(`/accounts/${encodeURIComponent(accountId)}/ledger`, token);
}

export function listPaperOrders(accountId: string, token: string): Promise<{ orders: PaperOrder[] }> {
  return request(`/accounts/${encodeURIComponent(accountId)}/orders`, token);
}
