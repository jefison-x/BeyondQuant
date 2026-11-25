import { describe, expect, it } from "vitest";
import {
  buildResearchPreparationHandoffUrl,
  normalizeResearchPreparationScope,
  researchPreparationScopeFromHandoffQuery,
} from "./researchPreparation";

const validScope = {
  symbols: ["600036.SH"], start_date: "20260101", end_date: "20260629", use_case: "research",
  data_requirements: { daily_basic: ["pe_ttm", "pb"], fundamentals: ["roe"] },
};

describe("research preparation scope handoff", () => {
  it("accepts an explicit bounded scope and normalizes date and symbols", () => {
    expect(normalizeResearchPreparationScope({ ...validScope, symbols: [" 600036.sh "], start_date: "2026-01-01" }))
      .toEqual({ ...validScope, symbols: ["600036.SH"] });
  });

  it("rejects invalid symbols, reversed dates, excess scope, and unsupported fields", () => {
    expect(normalizeResearchPreparationScope({ ...validScope, symbols: ["600036"] })).toBeNull();
    expect(normalizeResearchPreparationScope({ ...validScope, start_date: "20260629", end_date: "20260101" })).toBeNull();
    expect(normalizeResearchPreparationScope({ ...validScope, end_date: "20260701" })).toBeNull();
    expect(normalizeResearchPreparationScope({ ...validScope, symbols: Array.from({ length: 21 }, () => "600036.SH") })).toBeNull();
    expect(normalizeResearchPreparationScope({ ...validScope, data_requirements: { daily_basic: ["invented_field"] } })).toBeNull();
  });

  it("creates a scope-only admin link and recovers the same scope", () => {
    const normalized = normalizeResearchPreparationScope(validScope)!;
    const url = new URL(buildResearchPreparationHandoffUrl(normalized, "https://byq.example"));
    const query = url.searchParams.get("researchPreparation");
    expect(url.pathname).toBe("/settings/system/data");
    expect(url.searchParams.has("session")).toBe(false);
    expect(url.searchParams.has("conversation_id")).toBe(false);
    expect(url.searchParams.has("user")).toBe(false);
    expect(researchPreparationScopeFromHandoffQuery(query)).toEqual(normalized);
    expect(researchPreparationScopeFromHandoffQuery("{" )).toBeNull();
  });

  it("accepts a ten-year index receipt without opening the manual stock handoff", () => {
    const receipt = {
      asset_type: "index", symbols: ["000300.SH", "000905.SH"], start_date: "20161125",
      end_date: "20261124", use_case: "research", data_requirements: {},
    };
    expect(normalizeResearchPreparationScope(receipt, { allowIndexHistory: true })).toEqual(receipt);
    expect(normalizeResearchPreparationScope(receipt)).toBeNull();
    expect(normalizeResearchPreparationScope({ ...receipt, symbols: ["600036.SH"] }, { allowIndexHistory: true })).toBeNull();
  });
});
