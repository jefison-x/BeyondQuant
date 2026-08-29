import type { PaperAccount, PaperControls, PaperLedgerEntry, PaperOrder, PaperSnapshot, StockPool, StockPoolSnapshot } from "./types";
import { createRequestId } from "@/utils/requestId";

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

export function deletePaperAccount(
  accountId: string,
  expectedVersion: number,
  token: string,
): Promise<{ account_id: string; deleted: boolean }> {
  return request(`/accounts/${encodeURIComponent(accountId)}`, token, {
    method: "DELETE",
    body: JSON.stringify({
      expected_version: expectedVersion,
      idempotency_key: createRequestId(),
      reason: "用户删除模拟账户",
    }),
  });
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
      pool_type: options.poolType ?? "custom",
      description: options.description ?? null,
      weights: options.weights ?? {},
    }),
  });
}

export function listStockPools(token: string): Promise<{ pools: Array<Record<string, unknown>> }> {
  return request(`/pools`, token);
}

export function getStockPool(poolId: string, token: string): Promise<{ pool: StockPool }> {
  return request(`/pools/${encodeURIComponent(poolId)}`, token);
}

export function updateStockPoolMetadata(
  poolId: string,
  payload: { name: string; description?: string; expected_metadata_version: number },
  token: string,
): Promise<{ pool: StockPool }> {
  return request(`/pools/${encodeURIComponent(poolId)}/metadata`, token, { method: "PATCH", body: JSON.stringify(payload) });
}

export function replaceStockPoolSnapshot(
  poolId: string,
  payload: Record<string, unknown>,
  token: string,
): Promise<{ snapshot: StockPoolSnapshot }> {
  return request(`/pools/${encodeURIComponent(poolId)}/snapshot`, token, { method: "PUT", body: JSON.stringify(payload) });
}

export function listStockPoolSnapshots(poolId: string, token: string): Promise<{ snapshots: StockPoolSnapshot[] }> {
  return request(`/pools/${encodeURIComponent(poolId)}/snapshots`, token);
}

export function getStockPoolSnapshot(poolId: string, snapshotId: string, token: string): Promise<{ snapshot: StockPoolSnapshot }> {
  return request(`/pools/${encodeURIComponent(poolId)}/snapshots/${encodeURIComponent(snapshotId)}`, token);
}

export function getStockPoolAsOf(poolId: string, tradeDate: string, token: string): Promise<{ snapshot: StockPoolSnapshot }> {
  return request(`/pools/${encodeURIComponent(poolId)}/as-of/${encodeURIComponent(tradeDate)}`, token);
}

export function listStockPoolReferences(poolId: string, token: string): Promise<{ references: Array<Record<string, unknown>> }> {
  return request(`/pools/${encodeURIComponent(poolId)}/references`, token);
}

export function setStockPoolLifecycle(
  poolId: string,
  status: "active" | "inactive",
  reason: string,
  token: string,
): Promise<{ pool: StockPool }> {
  return request(`/pools/${encodeURIComponent(poolId)}/lifecycle`, token, {
    method: "PATCH",
    body: JSON.stringify({ status, reason, idempotency_key: createRequestId() }),
  });
}

export function deleteStockPool(poolId: string, token: string): Promise<{ pool: StockPool }> {
  return request(`/pools/${encodeURIComponent(poolId)}`, token, {
    method: "DELETE",
    headers: { "x-idempotency-key": createRequestId() },
  });
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

export function getPaperOrder(accountId: string, orderId: string, token: string): Promise<{ order: PaperOrder }> {
  return request(`/accounts/${encodeURIComponent(accountId)}/orders/${encodeURIComponent(orderId)}`, token);
}

export function listPaperSnapshots(accountId: string, token: string): Promise<{ snapshots: PaperSnapshot[] }> {
  return request(`/accounts/${encodeURIComponent(accountId)}/snapshots`, token);
}

export function settlePaperAccount(
  accountId: string,
  payload: { trade_date: string; expected_version: number; idempotency_key: string; marks: Record<string, number> },
  token: string,
): Promise<{ snapshot: PaperSnapshot }> {
  return request(`/accounts/${encodeURIComponent(accountId)}/settlements`, token, { method: "POST", body: JSON.stringify(payload) });
}

export function getPaperControls(accountId: string, token: string): Promise<{ controls: PaperControls }> {
  return request(`/accounts/${encodeURIComponent(accountId)}/controls`, token);
}

export function updatePaperControls(
  accountId: string,
  payload: { kill_switch_engaged: boolean; kill_switch_reason?: string; max_order_notional?: number | null; expected_version: number; idempotency_key: string },
  token: string,
): Promise<{ controls: PaperControls }> {
  return request(`/accounts/${encodeURIComponent(accountId)}/controls`, token, { method: "PUT", body: JSON.stringify(payload) });
}

export function rebindPaperAccount(
  accountId: string,
  payload: { pool_id: string; expected_version: number; idempotency_key: string },
  token: string,
): Promise<{ account: PaperAccount }> {
  return request(`/accounts/${encodeURIComponent(accountId)}/binding`, token, { method: "PUT", body: JSON.stringify(payload) });
}

export function exportPaperAccount(accountId: string, token: string): Promise<{ bundle: Record<string, unknown> }> {
  return request(`/accounts/${encodeURIComponent(accountId)}/export`, token);
}

export function importPaperAccount(bundle: Record<string, unknown>, token: string): Promise<{ imported: boolean; account: PaperAccount }> {
  return request("/accounts/import", token, { method: "POST", body: JSON.stringify({ bundle }) });
}
