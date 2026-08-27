import { describe, expect, it } from "vitest";
import { boundedReadinessSymbols, stockPoolSymbols } from "./readinessInputs";

describe("readiness stock-pool inputs", () => {
  it("uses canonical direct symbols without duplicates", () => {
    expect(stockPoolSymbols({ symbols: ["600036.sh", "600036.SH", " 601166.SH "] })).toEqual([
      "600036.SH",
      "601166.SH",
    ]);
  });

  it("falls back to the immutable current snapshot", () => {
    expect(stockPoolSymbols({
      snapshot: {
        snapshot_id: "snapshot-1", pool_id: "pool-1", version_number: 1,
        membership_fingerprint: "member", snapshot_fingerprint: "snapshot",
        definition: {}, provenance: {}, weight_mode: "unweighted", member_count: 2,
        members: [{ symbol: "000001.SZ", weight: null }, { symbol: "600000.SH", weight: null }],
        created_at: "2026-08-27T00:00:00Z",
      },
    })).toEqual(["000001.SZ", "600000.SH"]);
  });

  it("never silently prepares more than the Product readiness bound", () => {
    const symbols = Array.from({ length: 25 }, (_, index) => `${String(index).padStart(6, "0")}.SZ`);
    expect(boundedReadinessSymbols(symbols)).toHaveLength(20);
    expect(boundedReadinessSymbols(symbols).at(-1)).toBe("000019.SZ");
  });
});
