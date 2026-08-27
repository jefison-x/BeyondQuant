import type { StockPool } from "@/api/types";

export function stockPoolSymbols(pool: StockPool): string[] {
  const direct = Array.isArray(pool.symbols) ? pool.symbols : [];
  const snapshot = Array.isArray(pool.snapshot?.members)
    ? pool.snapshot.members.map((member) => member.symbol)
    : [];
  return [...new Set([...direct, ...snapshot]
    .map((symbol) => String(symbol).trim().toUpperCase())
    .filter(Boolean))];
}

export function boundedReadinessSymbols(symbols: string[], limit = 20): string[] {
  return [...new Set(symbols.map((symbol) => symbol.trim().toUpperCase()).filter(Boolean))].slice(0, limit);
}
