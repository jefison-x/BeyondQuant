import { afterEach, describe, expect, it, vi } from "vitest";
import { beginTaskSubmission, finishTaskSubmission, readTaskSubmission } from "./taskSubmission";

describe("durable research submission identity", () => {
  afterEach(() => { localStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
  it("retains the original request across reload and refuses changed meaning", () => {
    const pending = beginTaskSubmission("alice:workspace-a", "Research A", "Original goal");
    expect(readTaskSubmission("alice:workspace-a")).toEqual(pending);
    expect(beginTaskSubmission("alice:workspace-a", "Research A", "Original goal")).toEqual(pending);
    expect(() => beginTaskSubmission("alice:workspace-a", "Research B", "Other goal")).toThrow("原任务");
    finishTaskSubmission("alice:workspace-a", "wrong-acknowledgement");
    expect(readTaskSubmission("alice:workspace-a")).toEqual(pending);
    finishTaskSubmission("alice:workspace-a", pending.key);
    expect(readTaskSubmission("alice:workspace-a")).toBeNull();
    expect(beginTaskSubmission("alice:workspace-a", "Research A", "Original goal").key).not.toBe(pending.key);
  });
  it("persists and reuses the original identity on non-secure HTTP origins", () => {
    const getRandomValues = vi.fn((bytes: Uint8Array) => { bytes.fill(17); return bytes; });
    vi.stubGlobal("crypto", { getRandomValues });
    const pending = beginTaskSubmission("alice:http", "Research", "Goal");
    expect(pending.key).toMatch(/^[a-zA-Z0-9_-]{8,96}$/);
    expect(readTaskSubmission("alice:http")).toEqual(pending);
    expect(beginTaskSubmission("alice:http", "Research", "Goal")).toEqual(pending);
    expect(getRandomValues).toHaveBeenCalledTimes(1);
    finishTaskSubmission("alice:http", "unrelated-receipt");
    expect(readTaskSubmission("alice:http")).toEqual(pending);
    finishTaskSubmission("alice:http", pending.key);
    expect(readTaskSubmission("alice:http")).toBeNull();
  });
  it("isolates owners and workspaces", () => {
    const pending = beginTaskSubmission("alice:workspace-a", "Research", "Goal");
    expect(readTaskSubmission("bob:workspace-a")).toBeNull();
    expect(readTaskSubmission("alice:workspace-b")).toBeNull();
    expect(beginTaskSubmission("bob:workspace-a", "Research", "Goal").key).not.toBe(pending.key);
  });
  it("fails closed if storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("storage denied"); });
    expect(() => beginTaskSubmission("alice", "Research", "Goal")).toThrow("storage denied");
  });
});
