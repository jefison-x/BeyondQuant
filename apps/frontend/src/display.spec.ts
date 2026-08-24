import { describe, expect, it } from "vitest";
import { formatCount, statusLabel } from "./display";

describe("display formatters", () => {
  it("normalizes common Product statuses without inventing unknown labels", () => {
    expect(statusLabel("completed")).toBe("已完成");
    expect(statusLabel("domain-specific")).toBe("domain-specific");
    expect(statusLabel(null)).toBe("未知");
  });

  it("formats finite counts for the active locale", () => {
    expect(formatCount(12345)).toBe("12,345");
    expect(formatCount("not-a-number")).toBe("-");
  });
});
